"""
risk/engine.py
---------------
Standalone risk guard enforcing configurable loss and exposure limits for backtesting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any

from config import IST_TZ
from risk.base import RiskEngineBase
from risk.models import RiskCheckResult, RiskCheckCode, RiskEvent
from risk.config import RiskConfig


class RiskEngine(RiskEngineBase):
    """
    Backtester Risk engine enforcing daily drawdowns and max position constraints.
    Inherits from RiskEngineBase to ensure parity with LiveRiskGuard.
    """

    def __repr__(self) -> str:
        return (
            f"<RiskEngine(cap={self.config.initial_capital}, "
            f"daily_loss={self.config.max_daily_loss_pct}%, "
            f"max_pos={self.config.max_positions}, "
            f"shorting={self.config.allow_shorting})>"
        )

    def _log_event(self, event_type: str, symbol: str, action: str, code: RiskCheckCode, reason: str, pv: float = 0.0) -> None:
        evt = RiskEvent(
            timestamp=datetime.now(tz=IST_TZ),
            event_type=event_type,
            symbol=symbol,
            action=action,
            code=code,
            reason=reason,
            portfolio_value=pv,
        )
        self._events.append(evt)

    def check_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        cash: float,
        open_positions: Dict[str, Any],
    ) -> RiskCheckResult:
        # 1. Kill Switch
        if self.state.kill_switch_active:
            res = RiskCheckResult.block(RiskCheckCode.KILL_SWITCH, "Kill switch is active")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # (Market Hours handled by config/intraday_squareoff for backtesting, skipped here)

        # 2. Halted (Drawdown or Daily Loss)
        if self.state.halted:
            res = RiskCheckResult.block(RiskCheckCode.HALTED, f"Trading halted: {self.state.halt_reason}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        order_cost = price * quantity

        # 3. Cash sufficiency check
        if action == "BUY" and order_cost > cash:
            res = RiskCheckResult.block(RiskCheckCode.INSUFFICIENT_CASH, f"Cost {order_cost} > Cash {cash}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # 4. Daily Loss Limit
        # Limit is max_daily_loss_pct % of initial_capital
        max_loss_abs = self.config.initial_capital * (self.config.max_daily_loss_pct / 100.0)
        if abs(self.state.daily_realized_loss) >= max_loss_abs:
            res = RiskCheckResult.block(RiskCheckCode.DAILY_LOSS_LIMIT, f"Daily realized loss {self.state.daily_realized_loss} hit limit {max_loss_abs}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # 5. Max Drawdown
        # Drawdown halt should already be caught by `halted` flag, but checking explicitly
        if self.state.peak_equity > 0:
            current_equity = cash + sum([pos.quantity * price for pos in open_positions.values()]) # rough estimate if pos is passed as objs with .quantity
            # For exact checking, we rely on record_equity, but let's do a basic check
            dd_pct = ((self.state.peak_equity - current_equity) / self.state.peak_equity) * 100.0
            if dd_pct >= self.config.max_drawdown_pct:
                res = RiskCheckResult.block(RiskCheckCode.MAX_DRAWDOWN, f"Current drawdown {dd_pct:.2f}% >= {self.config.max_drawdown_pct}% limit")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # 6. Short selling check
        if action == "SELL" and not self.config.allow_shorting:
            # Need to know if it's a new short entry or closing a long.
            # In live bot, closing is usually action="SELL" with open_positions[symbol].direction == 1
            # For RiskEngine, backtester calls check_order for new entries mostly, but let's assume if we don't hold it, it's a short.
            has_long = symbol in open_positions and getattr(open_positions[symbol], "direction", 0) == 1
            if not has_long:
                res = RiskCheckResult.block(RiskCheckCode.SHORT_NOT_ALLOWED, "Shorting is disabled")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # 7. Duplicate Position
        if symbol in open_positions:
            has_pos = True
            pos_dir = getattr(open_positions[symbol], "direction", 0)
            if pos_dir == 1 and action == "BUY":
                res = RiskCheckResult.block(RiskCheckCode.DUPLICATE_LONG, f"Duplicate long for {symbol}")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res
            elif pos_dir == -1 and action == "SELL":
                res = RiskCheckResult.block(RiskCheckCode.DUPLICATE_SHORT, f"Duplicate short for {symbol}")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # 8. Max Positions
        # If it's a new position
        if symbol not in open_positions and len(open_positions) >= self.config.max_positions:
            res = RiskCheckResult.block(RiskCheckCode.MAX_POSITIONS, f"Max positions ({self.config.max_positions}) reached")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # 9. Max Position Size %
        pv = cash + sum([getattr(pos, "quantity", 0) * price for pos in open_positions.values()])
        max_size_abs = pv * (self.config.max_position_size_pct / 100.0)
        if order_cost > max_size_abs:
            res = RiskCheckResult.block(RiskCheckCode.MAX_POSITION_SIZE, f"Order cost {order_cost} > Max position size {max_size_abs}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # Allowed
        self._log_event("ORDER_ALLOWED", symbol, action, RiskCheckCode.OK, "All checks passed", pv)
        return RiskCheckResult.ok()

    def record_equity(self, equity: float) -> None:
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity
            
        drawdown_pct = ((self.state.peak_equity - equity) / self.state.peak_equity) * 100.0 if self.state.peak_equity > 0 else 0.0
        if drawdown_pct >= self.config.max_drawdown_pct:
            if not self.state.halted:
                self.state.halted = True
                self.state.halt_reason = f"Max drawdown breached: {drawdown_pct:.2f}%"
                self._logger.warning(self.state.halt_reason)
                self._log_event("HALT", "ALL", "NONE", RiskCheckCode.MAX_DRAWDOWN, self.state.halt_reason, equity)

    def record_trade(self, pnl: float, is_loss: bool = False) -> None:
        self.state.trades_today += 1
        self.state.daily_net_pnl += pnl
        
        # In reality, the fill engine determines `is_loss`, or we can infer it if pnl < 0
        if pnl < 0 or is_loss:
            self.state.daily_realized_loss += pnl
            
        max_loss_abs = self.config.initial_capital * (self.config.max_daily_loss_pct / 100.0)
        if abs(self.state.daily_realized_loss) >= max_loss_abs:
            if not self.state.halted:
                self.state.halted = True
                self.state.halt_reason = f"Daily loss limit breached: {abs(self.state.daily_realized_loss):.2f}"
                self._logger.warning(self.state.halt_reason)
                self._log_event("HALT", "ALL", "NONE", RiskCheckCode.DAILY_LOSS_LIMIT, self.state.halt_reason)

    def can_open(self, current_positions: int, direction: int) -> bool:
        """
        Backward compatible simplified check for backtester event loop.
        Delegates basic checks to `check_order()` with dummy arguments, 
        but avoids constructing complex dummy position dicts just for size checks.
        """
        # For full backward compatibility where event_loop uses this for basic pre-checks:
        if self.state.halted or self.state.kill_switch_active:
            return False
            
        action = "BUY" if direction == 1 else "SELL"
        if direction == -1 and not self.config.allow_shorting:
            return False
            
        if current_positions >= self.config.max_positions:
            return False
            
        return True