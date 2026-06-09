"""
backtester/event_loop.py
-------------------------
The core bar-by-bar simulation loop.

This module has exactly ONE responsibility: iterate over ``signals_df``
one bar at a time and coordinate the fill engine and portfolio tracker.
All order-fill math lives in :mod:`fill_engine`.  All sizing math lives
in :mod:`position_sizer`.  All data structures live in :mod:`models`.

EXECUTION ORDER PER BAR
========================
On each bar ``i``:

1. **Update trailing-stop levels** and **check stop triggers** (trailing
   and fixed) via :meth:`FillEngine.check_stops`.
2. **Check pending limit / stop / stop-limit entry orders**.
3. **Intraday squareoff** (if enabled and time >= 15:20 IST).
4. **Process signal from the previous bar** — entries and exits execute
   at the *current* bar's open (next-bar execution model, no look-ahead).
5. **Record equity and drawdown** at this bar using NumPy arrays
   (converted to pd.Series only at the end — zero Pandas overhead per bar).
6. **Max drawdown guard** — halt if equity fell below the configured
   threshold, closing all positions immediately.

NO LOOK-AHEAD BIAS
==================
Signals are generated on bar ``i`` but executed on bar ``i+1``'s open.
The loop acts on ``signals[i-1]`` during bar ``i`` — strategies cannot
use bar ``i``'s OHLCV to fill at bar ``i``'s prices.

P0 FIX (2026-04-11)
===================
The end-of-data position close block was incorrectly indented one level
too deep — it sat *inside* the ``for i in range(n)`` loop rather than
after it. This caused it to run on every bar (using ``closes[-1]``, the
final-bar price, for all intermediate bars) and generated phantom "End
of Data" trades throughout the backtest. The block is now correctly
placed *outside* the loop so it fires exactly once after all bars have
been processed.

The unused ``position_sl`` dict (declared but never written or read) has
also been removed.
"""

from __future__ import annotations

import logging
from datetime import time as dtime
from typing import Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtester.models import BacktestConfig, Position, Trade, OrderType
from backtester.fill_engine import FillEngine
from backtester.order_types import PendingOrder
from backtester.position_sizer import compute_quantity
from risk.engine import RiskEngine

logger = logging.getLogger(__name__)

_SQUAREOFF_TIME = dtime(15, 20)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_event_loop(
    signals_df: pd.DataFrame,
    config:     BacktestConfig,
    symbol:     str,
    strategy:   Optional[Any] = None,
) -> Tuple[List[Trade], pd.Series, pd.Series]:
    """
    Run the bar-by-bar backtest simulation for one symbol.

    Parameters
    ----------
    signals_df : pd.DataFrame
        OHLCV data with a ``signal`` column appended by the strategy.
        Required columns: ``open``, ``high``, ``low``, ``close``, ``signal``.
    config : BacktestConfig
    symbol : str
    strategy : BaseStrategy, optional
        If provided, the engine calls strategy lifecycle hooks:
          - ``on_entry_stop()``  — per-trade stop-loss price
          - ``on_bar_close()``   — per-bar trailing stop update
          - ``on_size()``        — custom position sizing

    Returns
    -------
    trade_log : list[Trade]
    equity_curve : pd.Series  (same index as signals_df)
    drawdown : pd.Series      (fractional, <= 0)
    """
    cfg    = config
    filler = FillEngine(cfg)
    risk_engine = RiskEngine(cfg.risk_config)
    risk_engine.record_equity(cfg.initial_capital)

    # Extract NumPy arrays — avoids per-bar DataFrame attribute lookup
    closes  = signals_df["close"].values.astype(float)
    highs   = signals_df["high"].values.astype(float)
    lows    = signals_df["low"].values.astype(float)
    opens   = signals_df["open"].values.astype(float)
    signals = signals_df["signal"].fillna(0).astype(int).values
    times   = signals_df.index
    n       = len(signals_df)

    # Pre-compute ATR(14) once — used by position sizer each bar
    atr_vals = _compute_atr14(closes, highs, lows, n)

    # Mutable state
    cash:      float                = cfg.initial_capital
    positions: List[Position]       = []
    pending:   List[PendingOrder]   = []
    trade_log: List[Trade]          = []
    halted:    bool                 = False

    # Pre-allocated output arrays (NumPy write-by-index is ~100x faster than
    # pd.Series.iloc assignment inside a loop)
    equity_arr   = np.full(n, np.nan, dtype=float)
    drawdown_arr = np.full(n, np.nan, dtype=float)
    peak_equity  = cfg.initial_capital

    # ── Main event loop ────────────────────────────────────────────────────
    for i in range(n):
        op = opens[i];  hp = highs[i];  lp = lows[i];  cp = closes[i]
        ct = times[i]
        atr_i: Optional[float] = (
            float(atr_vals[i])
            if (atr_vals is not None and not np.isnan(atr_vals[i]))
            else None
        )

        # Skip bars with invalid open (corporate action gaps, bad data)
        if np.isnan(op) or op <= 0:
            equity_arr[i] = cash
            continue

        if halted or risk_engine.state.halted:
            equity_arr[i] = cash
            continue

        # Step 1: trailing + fixed stop checks
        port_val = _pv(cash, positions, cp)
        positions, fired, cash = filler.check_stops(
            positions, cash, op, hp, lp, ct, i, symbol, port_val
        )
        trade_log.extend(fired)

        # Step 2: pending entry orders
        pending, new_pos, cash = filler.check_pending_entries(
            pending, cash, op, hp, lp, ct, i, symbol, atr_i
        )
        positions.extend(new_pos)

        # Step 3: intraday squareoff
        if cfg.intraday_squareoff and _past_squareoff(ct):
            cash, positions, trade_log = _close_all(
                positions, cash, op, ct, i, filler, trade_log,
                "Intraday Squareoff", risk_engine=risk_engine,
            )

        # Step 3b: Hook — on_bar_close (trailing stop update per open position)
        # Called for every open position so strategies can implement custom
        # trailing stop logic (e.g. ORB's |prev_body|/5) without a custom loop.
        if strategy is not None and positions and i > 0 and hasattr(strategy, "on_bar_close"):
            row_i = signals_df.iloc[i]
            for pos in positions:
                old_sl = pos.stop_price if pos.stop_price is not None else float("nan")
                # Only invoke hook if position has a stop price (avoids NaN handling)
                if not _isnan(old_sl):
                    new_sl = strategy.on_bar_close(
                        bar_idx    = i,
                        row        = row_i,
                        direction  = pos.direction,
                        current_sl = old_sl,
                    )
                    # Hook must only move the stop in the favourable direction
                    if pos.direction == 1:
                        pos.stop_price = max(old_sl, new_sl) if new_sl > old_sl else old_sl
                    else:
                        pos.stop_price = min(old_sl, new_sl) if new_sl < old_sl else old_sl

        # Step 4: signal from PREVIOUS bar (next-bar execution — no look-ahead)
        if i > 0 and signals[i - 1] != 0:
            if not risk_engine.can_open(len(positions), signals[i - 1]):
                logger.debug("RiskEngine blocked new trade at bar %s", i)
            else:
                cash, positions, pending, trade_log = _handle_signal(
                    signal=int(signals[i - 1]),
                    exec_price=op, prev_close=closes[i - 1],
                    bar_time=ct, bar_idx=i, cash=cash, atr=atr_i,
                    positions=positions, pending=pending,
                    trade_log=trade_log, filler=filler, cfg=cfg, symbol=symbol,
                    strategy=strategy,
                    signal_row=signals_df.iloc[i - 1],
                    risk_engine=risk_engine,
                )

        # Step 5: record equity and drawdown
        equity = _pv(cash, positions, cp)
        equity_arr[i] = equity
        if equity > peak_equity:
            peak_equity = equity
        drawdown_arr[i] = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0.0

        # Step 6: max drawdown halt
        if peak_equity > 0 and (equity / peak_equity - 1.0) < -cfg.max_drawdown_pct:
            logger.warning(f"[{symbol}] Max drawdown limit breached at bar {i}. Halting.")
            cash, positions, trade_log = _close_all(
                positions, cash, cp, ct, i, filler, trade_log,
                "Max Drawdown Halt", risk_engine=risk_engine,
            )
            halted = True

    # ── Force-close any surviving positions at end of data ─────────────────
    # P0 FIX: this block was previously indented one level too deep (inside
    # the for-loop above). It now correctly sits outside the loop and fires
    # exactly once after all bars have been processed.
    #
    # A surviving position here means the strategy emitted a sell/cover
    # signal on the very last bar — that signal would have executed at the
    # NEXT bar's open, which does not exist. We close it at the last close.
    if positions:
        lp_ = closes[-1]
        lt_ = times[-1]
        pv_ = _pv(cash, positions, lp_)
        for pos in list(positions):
            trade, cash = filler.close_position(
                pos, lp_, cash, lt_, n - 1, "End of Data", pv_
            )
            trade_log.append(trade)
            risk_engine.record_trade(trade.net_pnl)

    eq_series = pd.Series(equity_arr,   index=times, dtype=float)
    dd_series = pd.Series(drawdown_arr, index=times, dtype=float)

    final_eq = eq_series.dropna()
    if not final_eq.empty:
        logger.info(
            f"[{symbol}] {len(trade_log)} trades | "
            f"final equity=₹{float(final_eq.iloc[-1]):,.2f}"
        )
    return trade_log, eq_series, dd_series


# ---------------------------------------------------------------------------
# Signal processing helper
# ---------------------------------------------------------------------------

def _handle_signal(
    signal:     int,
    exec_price: float,
    prev_close: float,
    bar_time,
    bar_idx:    int,
    cash:       float,
    atr:        Optional[float],
    positions:  List[Position],
    pending:    List[PendingOrder],
    trade_log:  List[Trade],
    filler:     FillEngine,
    cfg:        BacktestConfig,
    symbol:     str,
    strategy:   Optional[Any] = None,
    signal_row: Optional[Any] = None,
    risk_engine: Optional[RiskEngine] = None,
) -> Tuple[float, List[Position], List[PendingOrder], List[Trade]]:
    """
    Translate a strategy signal into order actions.

    When ``strategy`` is provided, calls lifecycle hooks:
      - ``on_entry_stop()`` to get a per-trade stop-loss price
      - ``on_size()``       to get a custom position quantity
    """
    ot = cfg.default_order_type

    # Close opposing positions
    remaining: List[Position] = []
    port_val = _pv(cash, positions, exec_price)
    for pos in positions:
        should_close = (
            (signal ==  1 and pos.direction == -1) or
            (signal == -1 and pos.direction ==  1)
        )
        if should_close:
            trade, cash = filler.close_position(
                pos, exec_price, cash, bar_time, bar_idx, "Signal Exit", port_val
            )
            trade_log.append(trade)
            if risk_engine:
                risk_engine.record_trade(trade.net_pnl)
        else:
            remaining.append(pos)
    positions = remaining

    # Guards
    if cfg.max_positions > 0 and len(positions) >= cfg.max_positions:
        return cash, positions, pending, trade_log
    if signal == -1 and not cfg.allow_shorting:
        return cash, positions, pending, trade_log

    # ── Hook: on_entry_stop — per-trade stop-loss price ───────────────────
    # Strategy hook takes precedence over config's stop_loss_pct
    stop_price: Optional[float] = None
    if strategy is not None and signal_row is not None and hasattr(strategy, "on_entry_stop"):
        hook_sl = strategy.on_entry_stop(
            bar_idx   = bar_idx,
            row       = signal_row,
            direction = signal,
        )
        if hook_sl is not None:
            stop_price = float(hook_sl)

    # Fallback: use config-level stop if hook returned None
    if stop_price is None:
        stop_price = _entry_stop(signal, exec_price, atr, cfg)

    # ── Hook: on_size — custom position quantity ─────────────────────────
    custom_qty: Optional[int] = None
    if strategy is not None and signal_row is not None and hasattr(strategy, "on_size"):
        custom_qty = strategy.on_size(
            cash    = cash,
            price   = exec_price,
            bar_idx = bar_idx,
            row     = signal_row,
        )

    # Route by order type
    if ot == OrderType.MARKET:
        if custom_qty is not None and custom_qty > 0:
            # Custom sizing: build position directly, bypass FillEngine sizing
            from broker.upstox.commission import CommissionModel
            order_side = "BUY" if signal == 1 else "SELL"
            chg        = cfg.commission_model.calculate(
                cfg.segment, order_side, custom_qty, exec_price
            )
            total_cost = (exec_price * custom_qty + chg.total) if signal == 1 else chg.total
            if total_cost <= cash:
                from backtester.models import Position as _Pos
                pos = _Pos(
                    symbol        = symbol,
                    entry_time    = bar_time,
                    entry_price   = exec_price,
                    quantity      = custom_qty,
                    direction     = signal,
                    entry_signal  = "Market Signal",
                    entry_charges = chg.total,
                    entry_bar_idx = bar_idx,
                    stop_price    = stop_price,
                    order_type    = OrderType.MARKET,
                )
                cash -= total_cost
                positions.append(pos)
        else:
            pos, cash = filler.open_position(
                direction=signal, exec_price=exec_price, cash=cash,
                symbol=symbol, bar_idx=bar_idx, bar_time=bar_time,
                entry_signal="Market Signal", atr=atr, stop_price=stop_price,
            )
            if pos:
                positions.append(pos)

    else:
        pct = cfg.limit_offset_pct / 100.0
        qty = compute_quantity(
            cash, exec_price, cfg.capital_risk_pct,
            cfg.fixed_quantity, stop_price, atr, cfg.stop_loss_atr_mult,
        )
        if qty > 0:
            if ot == OrderType.LIMIT:
                lp = prev_close * (1.0 - pct) if signal == 1 else prev_close * (1.0 + pct)
                pending.append(PendingOrder(
                    direction=signal, order_type=OrderType.LIMIT,
                    quantity=qty, signal_bar=bar_idx, limit_price=lp,
                ))

            elif ot == OrderType.STOP:
                sp = prev_close * (1.0 + pct) if signal == 1 else prev_close * (1.0 - pct)
                pending.append(PendingOrder(
                    direction=signal, order_type=OrderType.STOP,
                    quantity=qty, signal_bar=bar_idx, stop_price=sp,
                ))

            elif ot == OrderType.STOP_LIMIT:
                sp  = prev_close * (1.0 + pct) if signal == 1 else prev_close * (1.0 - pct)
                lim = sp * (1.0 + pct) if signal == 1 else sp * (1.0 - pct)
                pending.append(PendingOrder(
                    direction=signal, order_type=OrderType.STOP_LIMIT,
                    quantity=qty, signal_bar=bar_idx,
                    stop_price=sp, limit_price=lim,
                ))

    return cash, positions, pending, trade_log


# ---------------------------------------------------------------------------
# Micro-helpers (keep hot-path readable)
# ---------------------------------------------------------------------------

def _pv(cash: float, positions: List[Position], price: float) -> float:
    """Portfolio value = cash + current market value of open positions."""
    return cash + sum(p.direction * p.quantity * price for p in positions)


def _close_all(
    positions:  List[Position],
    cash:       float,
    fill_price: float,
    bar_time,
    bar_idx:    int,
    filler:     FillEngine,
    trade_log:  List[Trade],
    reason:     str,
    risk_engine: Optional[RiskEngine] = None,
) -> Tuple[float, List[Position], List[Trade]]:
    """Close every open position at ``fill_price``."""
    port_val = _pv(cash, positions, fill_price)
    for pos in list(positions):
        trade, cash = filler.close_position(
            pos, fill_price, cash, bar_time, bar_idx, reason, port_val
        )
        trade_log.append(trade)
        if risk_engine:
            risk_engine.record_trade(trade.net_pnl)
    return cash, [], trade_log


def _past_squareoff(bar_time) -> bool:
    try:
        return bar_time.time() >= _SQUAREOFF_TIME
    except AttributeError:
        return False


def _entry_stop(
    direction: int, price: float, atr: Optional[float], cfg: BacktestConfig
) -> Optional[float]:
    """Compute fixed stop-loss price for a new entry (None if not configured)."""
    if cfg.stop_loss_pct > 0:
        dist = price * (cfg.stop_loss_pct / 100.0)
        return price - dist if direction == 1 else price + dist
    if atr and cfg.stop_loss_atr_mult > 0:
        dist = atr * cfg.stop_loss_atr_mult
        return price - dist if direction == 1 else price + dist
    return None


def _isnan(v) -> bool:
    """Safe NaN check that works for both float and numpy scalar."""
    try:
        import math
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


def _compute_atr14(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, n: int
) -> Optional[np.ndarray]:
    """
    Wilder's smoothed ATR(14) — vectorised pre-computation.

    Returns None for series shorter than 15 bars or on error.
    The first 14 values are NaN (warm-up period).
    """
    try:
        if n < 15:
            return None
        pc   = closes[:-1]
        tr   = np.maximum(highs[1:] - lows[1:],
               np.maximum(np.abs(highs[1:] - pc), np.abs(lows[1:] - pc)))
        atr  = np.full(n, np.nan, dtype=float)
        # Seed ATR with simple mean of first 14 TR values
        atr[14] = float(tr[:14].mean())
        for k in range(15, n):
            atr[k] = (atr[k - 1] * 13.0 + tr[k - 1]) / 14.0
        return atr
    except Exception as exc:
        logger.debug(f"ATR pre-computation error: {exc}")
        return None