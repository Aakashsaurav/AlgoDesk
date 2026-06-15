"""
backtester/event_loop.py
-------------------------
The core bar-by-bar simulation loop.
"""

from __future__ import annotations

import logging
from datetime import time as dtime
from typing import Any, List, Optional, Tuple, Dict

import numpy as np
import pandas as pd

from backtester.models import BacktestConfig, Position, Trade
from backtester.orders import OrderType, PendingOrder, GTTOrder
from backtester.fill_engine import FillEngine
from backtester.position_sizer import compute_quantity
from risk.engine import RiskEngine

logger = logging.getLogger(__name__)

_SQUAREOFF_TIME = dtime(15, 20)

def run_event_loop(
    signals_df: pd.DataFrame,
    config:     BacktestConfig,
    symbol:     str,
    strategy:   Optional[Any] = None,
    gtt_orders: Optional[List[GTTOrder]] = None,
) -> Tuple[List[Trade], pd.Series, pd.Series]:
    cfg    = config
    filler = FillEngine(cfg)
    risk_engine = RiskEngine(cfg.risk_config)
    risk_engine.record_equity(cfg.initial_capital)

    closes  = signals_df["close"].values.astype(float)
    highs   = signals_df["high"].values.astype(float)
    lows    = signals_df["low"].values.astype(float)
    opens   = signals_df["open"].values.astype(float)
    signals = signals_df["signal"].fillna(0).astype(int).values if "signal" in signals_df.columns else np.zeros(len(signals_df), dtype=int)
    
    if "signal_tag" in signals_df.columns:
        signal_tags = signals_df["signal_tag"].fillna("").astype(str).values
    else:
        signal_tags = np.full(len(signals_df), "", dtype=object)

    if "gtt_orders" in signals_df.columns:
        gtt_col = signals_df["gtt_orders"].values
    else:
        gtt_col = np.full(len(signals_df), None, dtype=object)

    times   = signals_df.index
    n       = len(signals_df)

    atr_vals = _compute_atr14(closes, highs, lows, n)

    cash:      float                = cfg.initial_capital
    positions: List[Position]       = []
    pending:   List[PendingOrder]   = []
    gtt_state: List[GTTOrder]       = list(gtt_orders) if gtt_orders else []
    trade_log: List[Trade]          = []
    halted:    bool                 = False

    equity_arr   = np.full(n, np.nan, dtype=float)
    drawdown_arr = np.full(n, np.nan, dtype=float)
    peak_equity  = cfg.initial_capital

    for i in range(n):
        op = opens[i];  hp = highs[i];  lp = lows[i];  cp = closes[i]
        ct = times[i]
        atr_i: Optional[float] = (
            float(atr_vals[i])
            if (atr_vals is not None and not np.isnan(atr_vals[i]))
            else None
        )

        if np.isnan(op) or op <= 0:
            equity_arr[i] = cash
            continue

        if halted or risk_engine.state.halted:
            equity_arr[i] = cash
            continue

        port_val = _pv(cash, positions, cp)
        
        positions, fired, cash = filler.check_exits(
            positions, cash, op, hp, lp, ct, i, symbol, port_val, atr_i,
            high_series=highs[:i+1], low_series=lows[:i+1]
        )
        trade_log.extend(fired)

        if gtt_col[i]:
            gtt_state.extend(gtt_col[i])
            
        gtt_state, new_pos_gtt, cash = filler.check_gtt_orders(
            gtt_state, cash, op, hp, lp, ct, i, symbol, atr_i, len(positions)
        )
        positions.extend(new_pos_gtt)

        pending, new_pos, cash = filler.check_pending_entries(
            pending, cash, op, hp, lp, ct, i, symbol, atr_i, len(positions)
        )
        positions.extend(new_pos)

        if cfg.intraday_squareoff and _past_squareoff(ct):
            cash, positions, trade_log = _close_all(
                positions, cash, op, ct, i, filler, trade_log,
                "Intraday Squareoff", risk_engine=risk_engine,
            )

        if strategy is not None and positions and i > 0 and hasattr(strategy, "on_bar_close"):
            for pos in positions:
                old_sl = pos.stop_price if pos.stop_price is not None else float("nan")
                if not _isnan(old_sl):
                    new_sl = strategy.on_bar_close(
                        bar_idx    = i,
                        open_p     = op,
                        high_p     = hp,
                        low_p      = lp,
                        close_p    = cp,
                        tag        = signal_tags[i],
                        direction  = pos.direction,
                        current_sl = old_sl,
                    )
                    if pos.direction == 1:
                        pos.stop_price = max(old_sl, new_sl) if new_sl > old_sl else old_sl
                    else:
                        pos.stop_price = min(old_sl, new_sl) if new_sl < old_sl else old_sl

        if i > 0 and signals[i - 1] != 0:
            if not risk_engine.can_open(len(positions), signals[i - 1]):
                logger.debug("RiskEngine blocked new trade at bar %s", i)
            else:
                tag = signal_tags[i-1] or "Market Signal"
                cash, positions, pending, trade_log = _handle_signal(
                    signal=int(signals[i - 1]),
                    exec_price=op, prev_close=closes[i - 1],
                    bar_time=ct, bar_idx=i, cash=cash, atr=atr_i,
                    positions=positions, pending=pending,
                    trade_log=trade_log, filler=filler, cfg=cfg, symbol=symbol,
                    strategy=strategy,
                    signal_row=signals_df.iloc[i - 1] if strategy else None,
                    risk_engine=risk_engine,
                    tag=tag
                )

        equity = _pv(cash, positions, cp)
        equity_arr[i] = equity
        if equity > peak_equity:
            peak_equity = equity
        drawdown_arr[i] = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0.0

        if peak_equity > 0 and (equity / peak_equity - 1.0) < -cfg.max_drawdown_pct:
            logger.warning(f"[{symbol}] Max drawdown limit breached at bar {i}. Halting.")
            cash, positions, trade_log = _close_all(
                positions, cash, cp, ct, i, filler, trade_log,
                "Max Drawdown Halt", risk_engine=risk_engine,
            )
            halted = True

    if positions:
        lp_ = closes[-1]
        lt_ = times[-1]
        pv_ = _pv(cash, positions, lp_)
        for pos in list(positions):
            trade, cash, _ = filler.close_position(
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


def _merge_symbol_bars(symbol_signals: Dict[str, pd.DataFrame]) -> List[Tuple[pd.Timestamp, str, dict]]:
    events = []
    for symbol, df in symbol_signals.items():
        times = df.index
        opens = df["open"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        closes = df["close"].values.astype(float)
        signals = df["signal"].fillna(0).astype(int).values if "signal" in df.columns else np.zeros(len(df), dtype=int)
        tags = df["signal_tag"].fillna("").astype(str).values if "signal_tag" in df.columns else np.full(len(df), "", dtype=object)
        gtts = df["gtt_orders"].values if "gtt_orders" in df.columns else np.full(len(df), None, dtype=object)
        
        n = len(df)
        atr_vals = _compute_atr14(closes, highs, lows, n)
        
        for i in range(n):
            events.append((
                times[i], 
                symbol, 
                {
                    "i": i,
                    "open": opens[i],
                    "high": highs[i],
                    "low": lows[i],
                    "close": closes[i],
                    "signal": signals[i],
                    "prev_signal": signals[i-1] if i > 0 else 0,
                    "prev_tag": tags[i-1] if i > 0 else "",
                    "prev_close": closes[i-1] if i > 0 else 0.0,
                    "prev_row": df.iloc[i-1] if i > 0 else None,
                    "tag": tags[i],
                    "gtt": gtts[i],
                    "atr": float(atr_vals[i]) if (atr_vals is not None and not np.isnan(atr_vals[i])) else None,
                    "high_series": highs[:i+1],
                    "low_series": lows[:i+1]
                }
            ))
            
    events.sort(key=lambda x: x[0])
    return events


def run_event_loop_portfolio(
    symbol_signals: Dict[str, pd.DataFrame],
    config: BacktestConfig,
    strategy_name: str = "",
) -> Tuple[List[Trade], Dict[str, pd.Series], pd.Series, pd.Series]:
    cfg = config
    filler = FillEngine(cfg)
    risk_engine = RiskEngine(cfg.risk_config)
    risk_engine.record_equity(cfg.initial_capital)

    cash = cfg.initial_capital
    positions_by_symbol: Dict[str, List[Position]] = {sym: [] for sym in symbol_signals}
    pending_by_symbol: Dict[str, List[PendingOrder]] = {sym: [] for sym in symbol_signals}
    gtt_by_symbol: Dict[str, List[GTTOrder]] = {sym: [] for sym in symbol_signals}
    trade_log: List[Trade] = []
    
    events = _merge_symbol_bars(symbol_signals)
    
    unique_times = sorted(list(set([e[0] for e in events])))
    combined_eq_dict = {t: np.nan for t in unique_times}
    per_sym_eq_dict = {sym: {t: np.nan for t in unique_times} for sym in symbol_signals}
    
    last_close = {sym: 0.0 for sym in symbol_signals}
    
    peak_equity = cfg.initial_capital
    halted = False
    
    for ts, sym, data in events:
        if halted:
            break
            
        op, hp, lp, cp = data["open"], data["high"], data["low"], data["close"]
        idx = data["i"]
        atr_i = data["atr"]
        
        last_close[sym] = cp
        
        if np.isnan(op) or op <= 0:
            continue
            
        pos_list = positions_by_symbol[sym]
        pend_list = pending_by_symbol[sym]
        gtt_list = gtt_by_symbol[sym]
        
        port_val = _pv_portfolio(cash, positions_by_symbol, last_close)
        
        pos_list, fired, cash = filler.check_exits(
            pos_list, cash, op, hp, lp, ts, idx, sym, port_val, atr_i,
            high_series=data["high_series"], low_series=data["low_series"]
        )
        trade_log.extend(fired)
        
        if data["gtt"]:
            gtt_list.extend(data["gtt"])
            
        gtt_list, new_pos_gtt, cash = filler.check_gtt_orders(
            gtt_list, cash, op, hp, lp, ts, idx, sym, atr_i, len(pos_list)
        )
        pos_list.extend(new_pos_gtt)
        
        pend_list, new_pos, cash = filler.check_pending_entries(
            pend_list, cash, op, hp, lp, ts, idx, sym, atr_i, len(pos_list)
        )
        pos_list.extend(new_pos)
        
        if cfg.intraday_squareoff and _past_squareoff(ts):
            cash, pos_list, trade_log = _close_all(
                pos_list, cash, op, ts, idx, filler, trade_log,
                "Intraday Squareoff", risk_engine
            )
            
        prev_signal = data["prev_signal"]
        if prev_signal != 0:
            if not risk_engine.can_open(len(pos_list), prev_signal):
                logger.debug("Risk blocked %s", sym)
            else:
                tag = data["prev_tag"] or "Market Signal"
                cash, pos_list, pend_list, trade_log = _handle_signal(
                    signal=int(prev_signal), exec_price=op, prev_close=data["prev_close"],
                    bar_time=ts, bar_idx=idx, cash=cash, atr=atr_i,
                    positions=pos_list, pending=pend_list, trade_log=trade_log,
                    filler=filler, cfg=cfg, symbol=sym,
                    strategy=None, signal_row=data["prev_row"],
                    risk_engine=risk_engine, tag=tag
                )
                
        positions_by_symbol[sym] = pos_list
        pending_by_symbol[sym] = pend_list
        gtt_by_symbol[sym] = gtt_list
        
        eq = _pv_portfolio(cash, positions_by_symbol, last_close)
        combined_eq_dict[ts] = eq
        
        per_sym_eq_dict[sym][ts] = _allocate_cash_share(cash, positions_by_symbol, sym, last_close)
        
        if eq > peak_equity: peak_equity = eq
        
        if peak_equity > 0 and (eq / peak_equity - 1.0) < -cfg.max_drawdown_pct:
            logger.warning(f"Portfolio max drawdown breached.")
            for s, p_list in positions_by_symbol.items():
                cash, p_list, trade_log = _close_all(
                    p_list, cash, last_close[s], ts, idx, filler, trade_log,
                    "Max Drawdown Halt", risk_engine
                )
                positions_by_symbol[s] = p_list
            halted = True
            
    # Force close
    for sym, p_list in positions_by_symbol.items():
        if p_list:
            lp_ = last_close[sym]
            pv_ = _pv_portfolio(cash, positions_by_symbol, last_close)
            for pos in list(p_list):
                trade, cash, _ = filler.close_position(
                    pos, lp_, cash, ts, 0, "End of Data", pv_
                )
                trade_log.append(trade)
                risk_engine.record_trade(trade.net_pnl)
                
    combined_eq_series = pd.Series(combined_eq_dict).ffill()
    combined_dd_series = (combined_eq_series - combined_eq_series.cummax()) / combined_eq_series.cummax()
    
    per_sym_eq_series = {}
    for sym in symbol_signals:
        s = pd.Series(per_sym_eq_dict[sym]).ffill()
        per_sym_eq_series[sym] = s
        
    return trade_log, per_sym_eq_series, combined_eq_series, combined_dd_series

def _pv_portfolio(cash: float, positions_by_symbol: Dict[str, List[Position]], last_close: Dict[str, float]) -> float:
    total_pos_value = sum(
        sum(p.direction * p.quantity * last_close[sym] for p in pos_list)
        for sym, pos_list in positions_by_symbol.items()
    )
    return cash + total_pos_value

def _allocate_cash_share(cash: float, positions_by_symbol: Dict[str, List[Position]], target_symbol: str, last_close: Dict[str, float]) -> float:
    sym_pos_val = sum(p.direction * p.quantity * last_close[target_symbol] for p in positions_by_symbol[target_symbol])
    return (cash / max(1, len(positions_by_symbol))) + sym_pos_val

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
    tag:        str = "Market Signal",
) -> Tuple[float, List[Position], List[PendingOrder], List[Trade]]:
    ot = cfg.default_order_type

    remaining: List[Position] = []
    port_val = _pv(cash, positions, exec_price)
    for pos in positions:
        should_close = (
            (signal ==  1 and pos.direction == -1) or
            (signal == -1 and pos.direction ==  1)
        )
        if should_close:
            trade, cash, _ = filler.close_position(
                pos, exec_price, cash, bar_time, bar_idx, "Signal Exit", port_val
            )
            trade_log.append(trade)
            if risk_engine:
                risk_engine.record_trade(trade.net_pnl)
        else:
            remaining.append(pos)
    positions = remaining

    if cfg.max_positions > 0 and len(positions) >= cfg.max_positions:
        return cash, positions, pending, trade_log
    if signal == -1 and not cfg.allow_shorting:
        return cash, positions, pending, trade_log

    stop_price: Optional[float] = None
    if strategy is not None and signal_row is not None and hasattr(strategy, "on_entry_stop"):
        hook_sl = strategy.on_entry_stop(
            bar_idx   = bar_idx,
            row       = signal_row,
            direction = signal,
        )
        if hook_sl is not None:
            stop_price = float(hook_sl)

    if stop_price is None:
        stop_price = _entry_stop(signal, exec_price, atr, cfg)

    custom_qty: Optional[int] = None
    if strategy is not None and signal_row is not None and hasattr(strategy, "on_size"):
        custom_qty = strategy.on_size(
            cash    = cash,
            price   = exec_price,
            bar_idx = bar_idx,
            row     = signal_row,
        )

    if ot == OrderType.MARKET:
        if custom_qty is not None and custom_qty > 0:
            order_side = "BUY" if signal == 1 else "SELL"
            chg        = filler.commission.calculate(
                order_side, custom_qty, exec_price, cfg.segment
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
                    entry_signal  = tag,
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
                entry_signal=tag, atr=atr, stop_price=stop_price,
            )
            if pos:
                positions.append(pos)

    else:
        pct = cfg.limit_offset_pct / 100.0
        qty = compute_quantity(
            cash, exec_price, cfg.capital_risk_pct,
            cfg.fixed_quantity, stop_price, atr, cfg.stop_loss_atr_mult, cfg.lot_size
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

def _pv(cash: float, positions: List[Position], price: float) -> float:
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
    port_val = _pv(cash, positions, fill_price)
    for pos in list(positions):
        trade, cash, _ = filler.close_position(
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
    if cfg.stop_loss_pct > 0:
        dist = price * (cfg.stop_loss_pct / 100.0)
        return price - dist if direction == 1 else price + dist
    if atr and cfg.stop_loss_atr_mult > 0:
        dist = atr * cfg.stop_loss_atr_mult
        return price - dist if direction == 1 else price + dist
    return None

def _isnan(v) -> bool:
    try:
        import math
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True

def _compute_atr14(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, n: int
) -> Optional[np.ndarray]:
    try:
        if n < 15:
            return None
        pc   = closes[:-1]
        tr   = np.maximum(highs[1:] - lows[1:],
               np.maximum(np.abs(highs[1:] - pc), np.abs(lows[1:] - pc)))
        atr  = np.full(n, np.nan, dtype=float)
        atr[14] = float(tr[:14].mean())
        for k in range(15, n):
            atr[k] = (atr[k - 1] * 13.0 + tr[k - 1]) / 14.0
        return atr
    except Exception as exc:
        logger.debug(f"ATR pre-computation error: {exc}")
        return None