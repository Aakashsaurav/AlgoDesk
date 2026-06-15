"""
backtester/performance.py
--------------------------
Computes the full suite of performance metrics from a completed backtest.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional, Dict

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from backtester.models import BacktestConfig, Trade, PortfolioResult

logger = logging.getLogger(__name__)

RISK_FREE_RATE_ANNUAL = 0.065   # 6.5% India 10-yr G-Sec proxy
TRADING_DAYS_PER_YEAR = 252

def compute_monthly_returns(equity_curve: pd.Series) -> Dict[str, float]:
    """Compute monthly returns keyed by YYYY-MM."""
    monthly_returns = {}
    if equity_curve.empty:
        return monthly_returns
    try:
        if hasattr(equity_curve.index, "to_period"):
            eq_daily = equity_curve.resample("D").last().dropna()
            monthly_eq = eq_daily.resample("ME").last().dropna()
            m_ret = monthly_eq.pct_change().dropna() * 100.0
            for ts, val in m_ret.items():
                monthly_returns[str(ts)[:7]] = round(float(val), 2)
    except Exception as exc:
        logger.debug(f"compute_monthly_returns failed: {exc}")
    return monthly_returns

def compute_portfolio_performance(port_result: "PortfolioResult") -> dict:
    """Compute portfolio-level metrics."""
    m = compute_performance(
        trade_log=port_result.combined_trade_log,
        equity_curve=port_result.combined_equity_curve,
        config=port_result.config
    )
    
    # Pairwise correlation
    returns_dict = {}
    net_pnls = {}
    for sym, res in port_result.symbol_results.items():
        if res.equity_curve is not None and not res.equity_curve.empty:
            returns_dict[sym] = res.equity_curve.resample("D").last().pct_change().dropna()
        net_pnls[sym] = sum(t.net_pnl for t in res.trade_log)
        
    df_ret = pd.DataFrame(returns_dict)
    corr_matrix = df_ret.corr().fillna(0).to_dict() if not df_ret.empty else {}
    
    if net_pnls:
        best_symbol = max(net_pnls.items(), key=lambda x: x[1])[0]
        worst_symbol = min(net_pnls.items(), key=lambda x: x[1])[0]
        total_pnl = sum(net_pnls.values())
        symbol_contributions = {sym: (pnl / total_pnl * 100 if total_pnl != 0 else 0.0) for sym, pnl in net_pnls.items()}
    else:
        best_symbol = ""
        worst_symbol = ""
        symbol_contributions = {}
        
    m.update({
        "correlation_matrix": corr_matrix,
        "best_symbol": best_symbol,
        "worst_symbol": worst_symbol,
        "symbol_contributions": symbol_contributions,
    })
    return m

def compute_performance(
    trade_log:    List["Trade"],
    equity_curve: pd.Series,
    config:       "BacktestConfig",
) -> dict:
    initial_capital = config.initial_capital

    if equity_curve.empty or equity_curve.dropna().empty:
        logger.warning("Empty equity curve — returning zero metrics.")
        return _empty_metrics(initial_capital)

    eq = equity_curve.dropna()

    start_v = initial_capital
    end_v   = float(eq.iloc[-1])
    total_return_pct = ((end_v / start_v) - 1.0) * 100.0

    start_date = eq.index[0]
    end_date   = eq.index[-1]
    try:
        years = max((end_date - start_date).days / 365.25, 1 / 365.25)
    except Exception:
        years = 1.0

    cagr_pct = (((end_v / start_v) ** (1.0 / years)) - 1.0) * 100.0

    if hasattr(eq.index, "date"):
        try:
            eq_daily = eq.resample("D").last().dropna()
        except Exception:
            eq_daily = eq
    else:
        eq_daily = eq

    daily_returns = eq_daily.pct_change().dropna()

    ann_vol = float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) * 100.0

    rfr_daily = (1 + RISK_FREE_RATE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = daily_returns - rfr_daily
    sharpe = (
        float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
        if excess.std() > 0 else 0.0
    )

    downside = daily_returns[daily_returns < 0]
    sortino = (
        float(excess.mean() / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
        if len(downside) > 0 and downside.std() > 0 else 0.0
    )

    eq_arr  = eq.values.astype(float)
    peak    = np.maximum.accumulate(eq_arr)
    dd_arr  = np.where(peak > 0, (eq_arr - peak) / peak, 0.0)

    max_dd  = float(dd_arr.min()) * 100.0  # negative %
    avg_dd  = float(dd_arr[dd_arr < 0].mean()) * 100.0 if (dd_arr < 0).any() else 0.0

    in_dd = dd_arr < 0
    max_dd_dur = _max_run(in_dd)

    calmar = abs(cagr_pct / max_dd) if max_dd != 0 else 0.0

    threshold = 0.0
    gains  = daily_returns[daily_returns > threshold] - threshold
    losses = threshold - daily_returns[daily_returns <= threshold]
    omega  = float(gains.sum() / losses.sum()) if losses.sum() > 0 else (999.0 if gains.sum() > 0 else 0.0)

    monthly_returns = compute_monthly_returns(eq)
    annual_returns:  dict = {}
    try:
        if hasattr(eq_daily.index, "to_period"):
            annual_eq = eq_daily.resample("YE").last().dropna()
            a_ret     = annual_eq.pct_change().dropna() * 100.0
            for ts, val in a_ret.items():
                annual_returns[str(ts)[:4]] = round(float(val), 2)
    except Exception as exc:
        logger.debug(f"Annual breakdown skipped: {exc}")

    trade_stats = _compute_trade_stats(trade_log)

    wr   = trade_stats["win_rate_pct"] / 100.0
    lr   = 1.0 - wr
    aw   = trade_stats["avg_win_inr"]
    al   = abs(trade_stats["avg_loss_inr"])
    kelly = ((wr * aw - lr * al) / aw) if aw > 0 else 0.0

    exposure_pct = _compute_exposure(trade_log, eq) if trade_log else 0.0

    total_commission = sum(t.total_charges for t in trade_log) if trade_log else 0.0
    brokerage_drag_pct = (total_commission / initial_capital) * 100.0 if initial_capital > 0 else 0.0
    net_return_after_tax_pct = total_return_pct - brokerage_drag_pct
    
    durations_days = [(t.exit_time - t.entry_time).days for t in trade_log] if trade_log else []
    avg_holding_days = float(np.mean(durations_days)) if durations_days else 0.0
    trades_per_month = len(trade_log) / (years * 12) if years > 0 else 0.0
    
    dd_inr_arr = eq_arr - peak
    max_dd_inr = float(dd_inr_arr.min()) if len(dd_inr_arr) > 0 else 0.0
    total_net_pnl = end_v - start_v
    recovery_factor = total_net_pnl / abs(max_dd_inr) if max_dd_inr < 0 else (999.0 if total_net_pnl > 0 else 0.0)

    return {
        "start_date":                str(start_date)[:10],
        "end_date":                  str(end_date)[:10],
        "initial_capital":           round(initial_capital, 2),
        "final_capital":             round(end_v, 2),
        "total_net_pnl":             round(total_net_pnl, 2),
        "total_return_pct":          round(total_return_pct, 4),
        "cagr_pct":                  round(cagr_pct, 4),
        "annualised_volatility":     round(ann_vol, 4),
        "sharpe_ratio":              round(sharpe, 4),
        "sortino_ratio":             round(sortino, 4),
        "calmar_ratio":              round(calmar, 4),
        "omega_ratio":               round(omega, 4),
        "kelly_fraction":            round(kelly, 4),
        "max_drawdown_pct":          round(max_dd, 4),
        "avg_drawdown_pct":          round(avg_dd, 4),
        "max_drawdown_duration_bars": int(max_dd_dur),
        "recovery_factor":           round(recovery_factor, 4),
        "brokerage_drag_pct":        round(brokerage_drag_pct, 4),
        "net_return_after_tax_pct":  round(net_return_after_tax_pct, 4),
        "avg_holding_days":          round(avg_holding_days, 2),
        "trades_per_month":          round(trades_per_month, 2),
        **trade_stats,
        "monthly_returns":           monthly_returns,
        "annual_returns":            annual_returns,
        "exposure_pct":              round(exposure_pct, 4),
        "total_commission_paid":     round(total_commission, 2),
    }

def _compute_trade_stats(trade_log: List["Trade"]) -> dict:
    empty = _empty_trade_stats()
    if not trade_log:
        return empty

    net_pnls    = np.array([t.net_pnl       for t in trade_log], dtype=float)
    durations   = np.array([t.duration_bars  for t in trade_log], dtype=float)
    mae_vals    = np.array([t.mae * t.quantity for t in trade_log], dtype=float)
    mfe_vals    = np.array([t.mfe * t.quantity for t in trade_log], dtype=float)

    winners = net_pnls[net_pnls > 0]
    losers  = net_pnls[net_pnls <= 0]
    n_total = len(net_pnls)
    n_win   = len(winners)
    n_loss  = len(losers)
    win_rate = (n_win / n_total) * 100.0 if n_total > 0 else 0.0

    avg_win  = float(winners.mean()) if n_win > 0 else 0.0
    avg_loss = float(losers.mean())  if n_loss > 0 else 0.0

    gross_wins  = winners.sum() if n_win > 0 else 0.0
    gross_loss  = abs(losers.sum()) if n_loss > 0 else 0.0
    pf = (gross_wins / gross_loss) if gross_loss > 0 else 999.0

    wr_frac  = win_rate / 100.0
    lr_frac  = 1.0 - wr_frac
    expectancy = (wr_frac * avg_win) + (lr_frac * avg_loss)

    is_win = net_pnls > 0
    is_loss = net_pnls <= 0

    largest_win_inr = float(winners.max()) if n_win > 0 else 0.0
    largest_loss_inr = float(losers.min()) if n_loss > 0 else 0.0
    risk_reward_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else 0.0

    reasons = [getattr(t, "exit_reason", "") for t in trade_log]
    stopped_out = sum(1 for r in reasons if "SL" in r or "Stop" in r or "Chandelier" in r)
    target_hit = sum(1 for r in reasons if "TARGET" in r or "Target" in r)
    time_exit = sum(1 for r in reasons if "TIME" in r or "Time" in r or "EOD" in r)
    
    pct_stopped_out = (stopped_out / n_total) * 100.0
    pct_target_hit = (target_hit / n_total) * 100.0
    pct_time_exit = (time_exit / n_total) * 100.0
    pct_signal_exit = 100.0 - pct_stopped_out - pct_target_hit - pct_time_exit
    if pct_signal_exit < 0:
        pct_signal_exit = 0.0

    return {
        "total_trades":            n_total,
        "winning_trades":          int(n_win),
        "losing_trades":           int(n_loss),
        "win_rate_pct":            round(win_rate, 4),
        "avg_win_inr":             round(avg_win,  2),
        "avg_loss_inr":            round(avg_loss, 2),
        "largest_win_inr":         round(largest_win_inr, 2),
        "largest_loss_inr":        round(largest_loss_inr, 2),
        "profit_factor":           round(pf,       4),
        "expectancy_inr":          round(expectancy, 2),
        "risk_reward_ratio":       round(risk_reward_ratio, 4),
        "avg_trade_duration_bars": round(float(durations.mean()), 2) if len(durations) > 0 else 0.0,
        "max_consecutive_wins":    int(_max_run(is_win)),
        "max_consecutive_losses":  int(_max_run(is_loss)),
        "avg_mae_inr":             round(float(mae_vals.mean()), 2) if len(mae_vals) > 0 else 0.0,
        "avg_mfe_inr":             round(float(mfe_vals.mean()), 2) if len(mfe_vals) > 0 else 0.0,
        "pct_stopped_out":         round(pct_stopped_out, 2),
        "pct_target_hit":          round(pct_target_hit, 2),
        "pct_signal_exit":         round(pct_signal_exit, 2),
        "pct_time_exit":           round(pct_time_exit, 2),
        "avg_sl_distance_pct":     0.0, # Cannot reliably calculate without modifying Trade model everywhere
    }

def _compute_exposure(trade_log: List["Trade"], equity_curve: pd.Series) -> float:
    if not trade_log or equity_curve.empty:
        return 0.0
    try:
        total_bars = len(equity_curve)
        if total_bars == 0:
            return 0.0
            
        in_trade = np.zeros(total_bars, dtype=bool)
        idx = equity_curve.index
        
        for t in trade_log:
            start_idx = idx.searchsorted(t.entry_time)
            end_idx = idx.searchsorted(t.exit_time, side="right")
            if end_idx > total_bars:
                end_idx = total_bars
            if start_idx < end_idx:
                in_trade[start_idx:end_idx] = True

        return float(in_trade.sum() / total_bars * 100.0)
    except Exception as exc:
        logger.debug(f"exposure_pct computation failed: {exc}")
        return 0.0

def _max_run(bool_arr) -> int:
    max_run = cur_run = 0
    for val in bool_arr:
        if val:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    return max_run

def _empty_trade_stats() -> dict:
    return {
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "win_rate_pct": 0.0, "avg_win_inr": 0.0, "avg_loss_inr": 0.0,
        "largest_win_inr": 0.0, "largest_loss_inr": 0.0,
        "profit_factor": 0.0, "expectancy_inr": 0.0, "risk_reward_ratio": 0.0,
        "avg_trade_duration_bars": 0.0, "max_consecutive_wins": 0,
        "max_consecutive_losses": 0, "avg_mae_inr": 0.0, "avg_mfe_inr": 0.0,
        "pct_stopped_out": 0.0, "pct_target_hit": 0.0, "pct_signal_exit": 0.0,
        "pct_time_exit": 0.0, "avg_sl_distance_pct": 0.0,
    }

def _empty_metrics(initial_capital: float) -> dict:
    m = _empty_trade_stats()
    m.update({
        "start_date": "", "end_date": "",
        "initial_capital": round(initial_capital, 2),
        "final_capital": round(initial_capital, 2),
        "total_net_pnl": 0.0,
        "total_return_pct": 0.0, "cagr_pct": 0.0,
        "annualised_volatility": 0.0, "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0, "calmar_ratio": 0.0,
        "omega_ratio": 0.0, "kelly_fraction": 0.0,
        "max_drawdown_pct": 0.0, "avg_drawdown_pct": 0.0,
        "max_drawdown_duration_bars": 0,
        "recovery_factor": 0.0, "brokerage_drag_pct": 0.0,
        "net_return_after_tax_pct": 0.0, "avg_holding_days": 0.0,
        "trades_per_month": 0.0,
        "monthly_returns": {}, "annual_returns": {},
        "exposure_pct": 0.0, "total_commission_paid": 0.0,
        "error": "No trades generated.",
    })
    return m
