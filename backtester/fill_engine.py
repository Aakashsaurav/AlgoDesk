"""
backtester/fill_engine.py
--------------------------
Order fill and position lifecycle logic.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from backtester.models import BacktestConfig, Position, Trade
from backtester.orders import OrderType, PendingOrder, GTTOrder, StopLossSpec, TakeProfitSpec
from backtester.order_types import (
    check_limit_fill,
    check_stop_fill,
    check_stop_limit_fill,
    check_amo_fill,
)
from risk.position_sizer import compute_quantity
from backtester.commission import CommissionBase

logger = logging.getLogger(__name__)

def _max_affordable_qty(
    cash: float,
    price: float,
    desired_qty: int,
    commission: CommissionBase,
    segment: str,
    side: str,
    lot_size: int = 1
) -> int:
    """Binary search to find max quantity affordable after commissions."""
    if cash <= 0 or price <= 0 or desired_qty <= 0:
        return 0
    low = 0
    high = desired_qty
    best = 0
    iterations = 0
    while low <= high and iterations < 20:
        iterations += 1
        mid = (low + high) // 2
        mid = (mid // lot_size) * lot_size
        if mid == 0:
            if low == high: break
            low = mid + 1
            continue
            
        chg = commission.calculate(side, mid, price, segment)
        total_cost = (price * mid) + chg.total if side == "BUY" else chg.total
        if cash >= total_cost:
            best = mid
            low = mid + lot_size
        else:
            high = mid - lot_size
    return best

class FillEngine:
    def __init__(self, config: BacktestConfig) -> None:
        self.cfg        = config
        self.commission = config.commission

    def open_position(
        self,
        direction:    int,
        exec_price:   float,
        cash:         float,
        symbol:       str,
        bar_idx:      int,
        bar_time:     pd.Timestamp,
        entry_signal: str,
        existing_positions: int = 0,
        atr:          Optional[float] = None,
        stop_price:   Optional[float] = None,
        sl_spec:      Optional[StopLossSpec] = None,
        tp_spec:      Optional[TakeProfitSpec] = None,
        gtt_order:    Optional[GTTOrder] = None,
    ) -> Tuple[Optional[Position], float]:
        cfg = self.cfg
        
        # Pyramiding check
        if existing_positions >= cfg.pyramid_max:
            return None, cash

        # Add Slippage
        slippage_factor = (1 + cfg.slippage_pct / 100.0) if direction == 1 else (1 - cfg.slippage_pct / 100.0)
        fill_price = exec_price * slippage_factor
        slippage_applied = abs(fill_price - exec_price)
        
        qty = compute_quantity(
            cash             = cash,
            entry_price      = fill_price,
            capital_risk_pct = cfg.capital_risk_pct,
            fixed_quantity   = cfg.fixed_quantity,
            stop_price       = stop_price,
            atr              = atr,
            atr_mult         = cfg.stop_loss_atr_mult,
            lot_size         = cfg.lot_size,
        )
        if qty <= 0:
            return None, cash

        order_side = "BUY" if direction == 1 else "SELL"
        
        if direction == 1:
            qty = _max_affordable_qty(cash, fill_price, qty, self.commission, cfg.segment, order_side, cfg.lot_size)
            if qty <= 0:
                return None, cash
                
        chg = self.commission.calculate(order_side, qty, fill_price, cfg.segment)
        total_cost = fill_price * qty + chg.total if direction == 1 else chg.total

        if cash < total_cost:
            return None, cash

        new_cash = cash - total_cost

        actual_sl_spec = sl_spec or StopLossSpec()
        actual_tp_spec = tp_spec or TakeProfitSpec()
        
        if actual_sl_spec.is_active() and stop_price is None:
            stop_price = actual_sl_spec.compute_initial_stop(fill_price, direction, atr)
            
        target_price = None
        if actual_tp_spec.is_active():
            sl_dist = abs(fill_price - stop_price) if stop_price else None
            target_price = actual_tp_spec.compute_target(fill_price, direction, sl_dist, atr)

        pos = Position(
            symbol              = symbol,
            entry_time          = bar_time,
            entry_price         = fill_price,
            quantity            = qty,
            direction           = direction,
            entry_signal        = entry_signal,
            entry_charges       = chg.total,
            entry_bar_idx       = bar_idx,
            stop_price          = stop_price,
            trailing_stop_pct   = cfg.trailing_stop_pct, 
            trailing_stop_amt   = cfg.trailing_stop_amt,
            trailing_stop_level = 0.0,
            order_type          = cfg.default_order_type,
            pyramid_level       = existing_positions + 1,
            slippage_applied    = slippage_applied * qty,
            sl_spec             = actual_sl_spec,
            tp_spec             = actual_tp_spec,
            target_price        = target_price,
            gtt_order           = gtt_order,
        )
        
        if cfg.use_trailing_stop:
            pos.update_trailing_stop(fill_price, fill_price)

        return pos, new_cash

    def open_bracket_position(
        self,
        direction: int,
        exec_price: float,
        sl_spec: StopLossSpec,
        tp_spec: TakeProfitSpec,
        cash: float,
        symbol: str,
        bar_idx: int,
        bar_time: pd.Timestamp,
        entry_signal: str,
        existing_positions: int = 0,
        atr: Optional[float] = None,
    ) -> Tuple[Optional[Position], float]:
        return self.open_position(
            direction=direction, exec_price=exec_price, cash=cash, symbol=symbol, 
            bar_idx=bar_idx, bar_time=bar_time, entry_signal=entry_signal, 
            existing_positions=existing_positions, atr=atr,
            sl_spec=sl_spec, tp_spec=tp_spec
        )

    def open_cover_position(
        self,
        direction: int,
        exec_price: float,
        sl_spec: StopLossSpec,
        cash: float,
        symbol: str,
        bar_idx: int,
        bar_time: pd.Timestamp,
        entry_signal: str,
        existing_positions: int = 0,
        atr: Optional[float] = None,
    ) -> Tuple[Optional[Position], float]:
        if not sl_spec.is_active():
            raise ValueError("Cover position requires an active StopLossSpec")
        return self.open_position(
            direction=direction, exec_price=exec_price, cash=cash, symbol=symbol, 
            bar_idx=bar_idx, bar_time=bar_time, entry_signal=entry_signal, 
            existing_positions=existing_positions, atr=atr,
            sl_spec=sl_spec
        )

    def close_position(
        self,
        pos:         Position,
        exec_price:  float,
        cash:        float,
        bar_time:    pd.Timestamp,
        bar_idx:     int,
        exit_signal: str,
        portfolio_value_after: float,
        partial_qty: Optional[int] = None,
    ) -> Tuple[Trade, float, Optional[Position]]:
        cfg = self.cfg
        order_side = "SELL" if pos.direction == 1 else "BUY"
        
        slippage_factor = (1 - cfg.slippage_pct / 100.0) if pos.direction == 1 else (1 + cfg.slippage_pct / 100.0)
        fill_price = exec_price * slippage_factor
        
        close_qty = partial_qty if partial_qty and partial_qty < pos.quantity else pos.quantity
        chg = self.commission.calculate(order_side, close_qty, fill_price, cfg.segment)

        gross_pnl = (fill_price - pos.entry_price) * pos.direction * close_qty
        
        alloc_entry_charges = pos.entry_charges * (close_qty / pos.quantity)
        net_pnl   = gross_pnl - alloc_entry_charges - chg.total
        pnl_pct   = net_pnl / (pos.entry_price * close_qty) if pos.entry_price > 0 else 0.0

        if pos.direction == 1:
            new_cash = cash + fill_price * close_qty - chg.total
        else:
            new_cash = cash + pos.entry_price * close_qty + gross_pnl - chg.total

        try:
            delta: timedelta = bar_time - pos.entry_time
            total_s = int(delta.total_seconds())
            d = total_s // 86400
            h = (total_s % 86400) // 3600
            m = (total_s % 3600)  // 60
            parts = []
            if d: parts.append(f"{d}d")
            if h: parts.append(f"{h}h")
            if m: parts.append(f"{m}m")
            duration_str = " ".join(parts) if parts else "< 1m"
        except Exception:
            duration_str = ""

        is_partial = close_qty < pos.quantity

        trade = Trade(
            symbol               = pos.symbol,
            entry_time           = pos.entry_time,
            exit_time            = bar_time,
            entry_price          = pos.entry_price,
            exit_price           = fill_price,
            quantity             = close_qty,
            direction            = pos.direction,
            direction_label      = pos.direction_label,
            gross_pnl            = round(gross_pnl, 2),
            entry_charges        = round(alloc_entry_charges, 2),
            exit_charges         = round(chg.total, 2),
            total_charges        = round(alloc_entry_charges + chg.total, 2),
            net_pnl              = round(net_pnl, 2),
            pnl_pct              = round(pnl_pct, 6),
            entry_signal         = pos.entry_signal,
            exit_signal          = exit_signal,
            duration             = duration_str,
            duration_bars        = bar_idx - pos.entry_bar_idx,
            mae                  = round(pos.mae, 4),
            mfe                  = round(pos.mfe, 4),
            cumulative_portfolio = round(portfolio_value_after, 2),
            pyramid_level        = pos.pyramid_level,
            slippage             = abs(fill_price - exec_price) * close_qty,
            sl_type              = pos.sl_spec.sl_type.value if pos.sl_spec else "",
            tp_type              = pos.tp_spec.tp_type.value if pos.tp_spec else "",
            exit_reason          = exit_signal,
            partial              = is_partial
        )

        if is_partial:
            pos.quantity -= close_qty
            pos.entry_charges -= alloc_entry_charges
            pos.partial_exit_done = True
            return trade, new_cash, pos
        else:
            return trade, new_cash, None

    def check_exits(
        self,
        positions: List[Position],
        cash:      float,
        open_p:    float,
        high:      float,
        low:       float,
        ct:        pd.Timestamp,
        bar_idx:   int,
        symbol:    str,
        portfolio_value: float,
        atr:       Optional[float] = None,
        high_series: Optional[np.ndarray] = None,
        low_series:  Optional[np.ndarray] = None,
    ) -> Tuple[List[Position], List[Trade], float]:
        remaining: List[Position] = []
        new_trades: List[Trade]   = []

        for pos in positions:
            mid = (high + low) / 2.0
            pos.update_excursion(mid)
            
            period_high, period_low = high, low
            if pos.sl_spec and pos.sl_spec.is_trailing() and hasattr(pos, 'update_chandelier_stop'):
                if high_series is not None and low_series is not None:
                    pos.update_chandelier_stop(high_series, low_series, atr, bar_idx)
            
            pos.update_trailing_stop(high, low, atr, period_high)

            fired = False
            fill_price = 0.0
            reason = ""
            partial_qty = None

            if not fired:
                triggered, fp = pos.is_fixed_stop_triggered(open_p, low, high)
                if triggered:
                    fired, fill_price, reason = True, fp, "SL"

            if not fired:
                triggered, fp = pos.is_trailing_stop_triggered(open_p, low, high)
                if triggered:
                    fired, fill_price, reason = True, fp, "TRAILING_SL"

            if not fired:
                if pos.is_time_exit_due(bar_idx):
                    fired, fill_price, reason = True, open_p, "TIME"

            if not fired:
                triggered, fp = pos.is_target_triggered(open_p, low, high)
                if triggered:
                    if pos.tp_spec and pos.tp_spec.tp_type.is_partial() and not pos.partial_exit_done:
                        fired = True
                        fill_price = fp
                        reason = "PARTIAL_TARGET"
                        partial_qty = int(pos.quantity * (pos.tp_spec.partial_pct / 100.0))
                        partial_qty = (partial_qty // self.cfg.lot_size) * self.cfg.lot_size
                        if partial_qty == 0:
                            partial_qty = self.cfg.lot_size 
                            if partial_qty >= pos.quantity:
                                partial_qty = pos.quantity
                                reason = "TARGET"
                    else:
                        fired, fill_price, reason = True, fp, "TARGET"

            if fired:
                trade, cash, updated_pos = self.close_position(
                    pos, fill_price, cash, ct, bar_idx, reason, portfolio_value, partial_qty
                )
                new_trades.append(trade)
                if updated_pos:
                    remaining.append(updated_pos)
            else:
                remaining.append(pos)

        return remaining, new_trades, cash

    def check_pending_entries(
        self,
        pending:   List[PendingOrder],
        cash:      float,
        open_p:    float,
        high:      float,
        low:       float,
        bar_time:  pd.Timestamp,
        bar_idx:   int,
        symbol:    str,
        atr:       Optional[float],
        existing_positions: int,
    ) -> Tuple[List[PendingOrder], List[Position], float]:
        remaining_pending: List[PendingOrder] = []
        new_positions:     List[Position]     = []

        for order in pending:
            if order.expires_after > 0 and (bar_idx - order.signal_bar) > order.expires_after:
                continue

            filled = False
            fill_price = 0.0
            stop_already_triggered = getattr(order, "_stop_triggered", False)

            if order.order_type == OrderType.AMO:
                filled, fill_price = check_amo_fill(bar_idx, order.signal_bar, open_p)
            elif order.order_type == OrderType.LIMIT:
                filled, fill_price = check_limit_fill(order.direction, order.limit_price, open_p, low, high)
            elif order.order_type == OrderType.STOP:
                filled, fill_price = check_stop_fill(order.direction, order.stop_price, open_p, low, high)
            elif order.order_type == OrderType.STOP_LIMIT:
                filled, fill_price, hit = check_stop_limit_fill(
                    order.direction, order.stop_price, order.limit_price,
                    open_p, low, high, stop_already_triggered
                )
                order._stop_triggered = hit
            elif order.order_type == OrderType.BRACKET:
                filled, fill_price = check_limit_fill(order.direction, order.limit_price, open_p, low, high)
            elif order.order_type == OrderType.COVER:
                filled, fill_price = check_limit_fill(order.direction, order.limit_price, open_p, low, high)

            if filled:
                if order.order_type == OrderType.BRACKET:
                    pos, cash = self.open_bracket_position(
                        order.direction, fill_price, order.sl_spec, order.tp_spec,
                        cash, symbol, bar_idx, bar_time, f"{order.order_type.value} Fill",
                        existing_positions + len(new_positions), atr
                    )
                elif order.order_type == OrderType.COVER:
                    pos, cash = self.open_cover_position(
                        order.direction, fill_price, order.sl_spec,
                        cash, symbol, bar_idx, bar_time, f"{order.order_type.value} Fill",
                        existing_positions + len(new_positions), atr
                    )
                else:
                    pos, cash = self.open_position(
                        direction    = order.direction,
                        exec_price   = fill_price,
                        cash         = cash,
                        symbol       = symbol,
                        bar_idx      = bar_idx,
                        bar_time     = bar_time,
                        entry_signal = f"{order.order_type.value} Fill",
                        existing_positions = existing_positions + len(new_positions),
                        atr          = atr,
                        sl_spec      = order.sl_spec,
                        tp_spec      = order.tp_spec,
                    )
                    
                if pos:
                    new_positions.append(pos)
            else:
                remaining_pending.append(order)

        return remaining_pending, new_positions, cash

    def check_gtt_orders(
        self,
        gtt_orders: List[GTTOrder],
        cash:       float,
        open_p:     float,
        high:       float,
        low:        float,
        bar_time:   pd.Timestamp,
        bar_idx:    int,
        symbol:     str,
        atr:        Optional[float],
        existing_positions: int,
    ) -> Tuple[List[GTTOrder], List[Position], float]:
        remaining: List[GTTOrder] = []
        new_positions: List[Position] = []

        for order in gtt_orders:
            if order.expiry_bars > 0 and (bar_idx - order.signal_bar) > order.expiry_bars:
                continue
                
            filled = False
            fill_price = 0.0

            if not order.triggered:
                if order.direction == 1:
                    if open_p >= order.trigger_price: order.triggered = True
                    elif high >= order.trigger_price: order.triggered = True
                else:
                    if open_p <= order.trigger_price: order.triggered = True
                    elif low <= order.trigger_price: order.triggered = True

            if order.triggered:
                if order.limit_price:
                    limit_filled, limit_fp = check_limit_fill(order.direction, order.limit_price, open_p, low, high)
                    if limit_filled:
                        filled, fill_price = True, limit_fp
                else:
                    if order.direction == 1:
                        fill_price = max(open_p, order.trigger_price)
                    else:
                        fill_price = min(open_p, order.trigger_price)
                    filled = True

            if filled:
                pos, cash = self.open_bracket_position(
                    order.direction, fill_price, order.sl_spec, order.tp_spec,
                    cash, symbol, bar_idx, bar_time, "GTT Fill",
                    existing_positions + len(new_positions), atr
                )
                if pos:
                    pos.gtt_order = order
                    new_positions.append(pos)
            else:
                remaining.append(order)

        return remaining, new_positions, cash