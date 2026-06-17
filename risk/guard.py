"""
risk/guard.py
-------------
Real-time risk management for the live trading engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Dict, Any, Optional

from config import IST_TZ
from risk.base import RiskEngineBase
from risk.models import RiskCheckResult, RiskCheckCode, RiskEvent
from risk.config import RiskConfig


class LiveRiskGuard(RiskEngineBase):
    """
    Live implementation of the risk engine. 
    State is managed centrally or passed in.
    """

    def __init__(self, config: RiskConfig) -> None:
        super().__init__(config)
        self._squareoff_triggered = False
        self._squareoff_date: Optional[date] = None

    def check_order(
        self,
        symbol: str,
        action: str,       # "BUY", "SELL", "SHORT", "COVER", "EXIT_ALL"
        quantity: int,
        price: float,
        cash: float,
        open_positions: Dict[str, Any],
    ) -> RiskCheckResult:
        """
        Run all pre-order risk checks.
        """
        # ── 1. Kill switch (highest priority) ────────────────────────────────
        if self.state.kill_switch_active:
            res = RiskCheckResult.block(RiskCheckCode.KILL_SWITCH, f"KILL_SWITCH: {self.state.halt_reason or 'Trading halted globally.'}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # Allow EXIT/SELL/COVER outside market hours (to close stuck positions)
        is_exit_action = action in ("SELL", "COVER", "EXIT_ALL")
        now_ist = datetime.now(tz=IST_TZ)
        current_time = now_ist.time()

        # ── 2. Market hours check ─────────────────────────────────────────────
        if not is_exit_action:
            if current_time < self.config.market_open_time:
                res = RiskCheckResult.block(RiskCheckCode.MARKET_CLOSED, f"MARKET_CLOSED: Opens at {self.config.market_open_time}. Current: {current_time}")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res
            if current_time >= self.config.market_close_time:
                res = RiskCheckResult.block(RiskCheckCode.MARKET_CLOSED, f"MARKET_CLOSED: Closed at {self.config.market_close_time}. Current: {current_time}")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # ── 3. Intraday squareoff time ────────────────────────────────────────
        if current_time >= self.config.squareoff_time and not is_exit_action:
            res = RiskCheckResult.block(RiskCheckCode.SQUAREOFF_TIME, f"SQUAREOFF_TIME: No new entries after {self.config.squareoff_time}.")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # ── 4. Cash sufficiency check (early) ─────────────────────────────────
        if action in ("BUY", "SHORT") and price > 0 and quantity > 0:
            required = price * quantity
            if required > cash:
                res = RiskCheckResult.block(RiskCheckCode.INSUFFICIENT_CASH, f"INSUFFICIENT_CASH: Need ₹{required:.0f}, have ₹{cash:.0f}.")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # ── 5. Daily loss limit ───────────────────────────────────────────────
        max_loss_abs = self.config.initial_capital * (self.config.max_daily_loss_pct / 100.0)
        if abs(self.state.daily_realized_loss) >= max_loss_abs and not is_exit_action:
            res = RiskCheckResult.block(RiskCheckCode.DAILY_LOSS_LIMIT, f"DAILY_LOSS_LIMIT: Realized loss {abs(self.state.daily_realized_loss):.2f} >= limit {max_loss_abs:.2f}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # ── 6. Max portfolio drawdown ─────────────────────────────────────────
        if self.state.halted and not is_exit_action: # Typically Max Drawdown triggers a halt
            res = RiskCheckResult.block(RiskCheckCode.MAX_DRAWDOWN, f"MAX_DRAWDOWN: {self.state.halt_reason}")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # We can also compute live drawdown if needed
        if self.state.peak_equity > 0:
            # We assume pv is cash + open positions value. For precise DD in live, record_equity handles it.
            pass

        # ── 7. Short selling guard ────────────────────────────────────────────
        if action == "SHORT" and not self.config.allow_shorting:
            res = RiskCheckResult.block(RiskCheckCode.SHORT_NOT_ALLOWED, "SHORT_NOT_ALLOWED: Short selling is disabled.")
            self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
            return res

        # ── 8. Duplicate position guard ───────────────────────────────────────
        if symbol in open_positions:
            pos_dir = getattr(open_positions[symbol], "direction", 0)
            if action == "BUY" and pos_dir > 0:
                res = RiskCheckResult.block(RiskCheckCode.DUPLICATE_LONG, f"DUPLICATE_LONG: Already long {symbol}.")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res
            if action == "SHORT" and pos_dir < 0:
                res = RiskCheckResult.block(RiskCheckCode.DUPLICATE_SHORT, f"DUPLICATE_SHORT: Already short {symbol}.")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # ── 9. Max open positions ─────────────────────────────────────────────
        if action in ("BUY", "SHORT") and symbol not in open_positions:
            n_positions = len(open_positions)
            if n_positions >= self.config.max_positions:
                res = RiskCheckResult.block(RiskCheckCode.MAX_POSITIONS, f"MAX_POSITIONS: Already at max {self.config.max_positions} open positions.")
                self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                return res

        # ── 10. Max position size (% of capital) ──────────────────────────────
        if action in ("BUY", "SHORT") and price > 0 and quantity > 0:
            order_value = price * quantity
            pv = cash + sum(getattr(p, "quantity", 0) * price for p in open_positions.values()) # Approx
            if pv > 0:
                position_pct = (order_value / pv) * 100
                if position_pct > self.config.max_position_size_pct:
                    res = RiskCheckResult.block(RiskCheckCode.MAX_POSITION_SIZE, f"MAX_POSITION_SIZE: Order value ₹{order_value:.0f} is {position_pct:.1f}% > {self.config.max_position_size_pct}% limit.")
                    self._log_event("ORDER_BLOCKED", symbol, action, res.code, res.reason)
                    return res

        # ── OK ────────────────────────────────────────────────────────────────
        self._log_event("ORDER_ALLOWED", symbol, action, RiskCheckCode.OK, "All checks passed")
        return RiskCheckResult.ok()

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

    def compute_position_size(
        self,
        price: float,
        stop_loss: Optional[float] = None,
        risk_pct_per_trade: float = 1.5,
        lot_size: int = 1,
        atr: Optional[float] = None,
        atr_multiplier: float = 2.0,
    ) -> int:
        """
        Calculate position size using the fixed-fractional risk model.
        """
        if price <= 0:
            return lot_size

        portfolio_value = self.state.peak_equity # Usually rely on peak or current equity
        if portfolio_value <= 0:
            return lot_size

        risk_amount = portfolio_value * (risk_pct_per_trade / 100.0)

        if stop_loss is not None and stop_loss > 0:
            risk_per_share = abs(price - stop_loss)
        elif atr is not None and atr > 0:
            risk_per_share = atr * atr_multiplier
        else:
            risk_per_share = price * 0.02  # Default: 2% of price

        if risk_per_share <= 0:
            return lot_size

        qty = int(risk_amount / risk_per_share)
        
        # Round down to nearest lot size
        if lot_size > 1:
            qty = (qty // lot_size) * lot_size

        qty = max(lot_size, qty)
        return qty

    def is_market_open(self) -> bool:
        from risk.holiday_calendar import calendar
        now_ist = datetime.now(tz=IST_TZ)
        today = now_ist.date()
        
        if not calendar.is_market_open_today(today):
            return False
            
        current_time = now_ist.time()
        return self.config.market_open_time <= current_time < self.config.market_close_time

    def should_squareoff_now(self) -> bool:
        today = date.today()
        now_time = datetime.now(tz=IST_TZ).time()

        if self._squareoff_date == today and self._squareoff_triggered:
            return False

        if now_time >= self.config.squareoff_time:
            self._squareoff_triggered = True
            self._squareoff_date = today
            return True

        return False

    def reset_daily_state(self) -> None:
        self._squareoff_triggered = False
        self._squareoff_date = None
        self.state.daily_realized_loss = 0.0
        self.state.daily_net_pnl = 0.0
        self.state.trades_today = 0
        self.state.halted = False
        self.state.halt_reason = ""
        self._logger.info("[RiskGuard] Daily state reset.")

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
        if pnl < 0 or is_loss:
            self.state.daily_realized_loss += pnl
            
        max_loss_abs = self.config.initial_capital * (self.config.max_daily_loss_pct / 100.0)
        if abs(self.state.daily_realized_loss) >= max_loss_abs:
            if not self.state.halted:
                self.state.halted = True
                self.state.halt_reason = f"Daily loss limit breached: {abs(self.state.daily_realized_loss):.2f}"
                self._logger.warning(self.state.halt_reason)
                self._log_event("HALT", "ALL", "NONE", RiskCheckCode.DAILY_LOSS_LIMIT, self.state.halt_reason)

