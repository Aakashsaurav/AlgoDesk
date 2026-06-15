# Use cases:
# - Canonical shared data structures for the standalone backtester module.
# - Single source of truth for config, positions, trades, and backtest results.
# - Serialization and summary helpers for engine, reporting, optimizer, and tests.
"""
backtester/models.py
---------------------
Single source of truth for every data structure used across the backtesting engine.

DESIGN RATIONALE
================
Previously, ``Trade``, ``Position``, ``BacktestConfig``, and ``BacktestResult`` were
scattered across ``engine.py``, ``engine_v2.py``, ``engine_old.py``, and
``portfolio.py`` — creating four partially-overlapping definitions with subtle
field differences. This module consolidates them into one canonical set.

No logic lives here. These are pure data containers. The engine, fill logic,
portfolio tracker, and performance module all import from here — ensuring that
a field rename requires only one edit in one file.

CONTENTS
========
  BacktestConfig    — all engine parameters in one place
  Trade             — one completed round-trip (entry + exit)
  Position          — one open position currently held
  BacktestResult    — output container from engine.run()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import time as dtime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from risk.config import RiskConfig

from backtester.config import BacktestConfig, SegmentPreset, INTRADAY_SQUAREOFF, TrailingType
from backtester.orders import (
    OrderType, StopLossType, TakeProfitType, StopLossSpec, TakeProfitSpec, GTTOrder
)


# ---------------------------------------------------------------------------
# Position  (one open trade currently held)
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """
    Represents a single open position.

    Created by :class:`backtester.fill_engine.FillEngine` when an entry order
    fills, and destroyed when the corresponding exit fills.

    Attributes
    ----------
    symbol : str
        Instrument symbol.
    entry_time : pd.Timestamp
        Bar timestamp at which the position was opened.
    entry_price : float
        Actual fill price (next-bar open after signal).
    quantity : int
        Number of shares / units held.
    direction : int
        +1 for LONG, -1 for SHORT.
    entry_signal : str
        Human-readable label for the entry reason (e.g. ``"Market Signal"``).
    entry_charges : float
        Total brokerage + taxes paid on entry.
    entry_bar_idx : int
        Integer index of the entry bar in the signal DataFrame.
    mae : float
        Maximum Adverse Excursion — worst unrealised loss since entry.
        Updated every bar by :meth:`update_excursion`.
    mfe : float
        Maximum Favourable Excursion — best unrealised profit since entry.
    stop_price : float or None
        Fixed stop-loss price (None if not configured).
    trailing_stop_pct : float
        Trailing stop % (0 = disabled).
    trailing_stop_amt : float
        Trailing stop ₹ amount (0 = disabled).
    trailing_stop_level : float
        Current trailing stop price (updated each bar).
    order_type : OrderType
        How the position was entered.
    """
    symbol:              str
    entry_time:          pd.Timestamp
    entry_price:         float
    quantity:            int
    direction:           int                 # +1 LONG, -1 SHORT
    entry_signal:        str   = ""
    entry_charges:       float = 0.0
    entry_bar_idx:       int   = 0
    mae:                 float = 0.0
    mfe:                 float = 0.0
    stop_price:          Optional[float] = None
    trailing_stop_pct:   float = 0.0
    trailing_stop_amt:   float = 0.0
    trailing_stop_level: float = 0.0
    order_type:          OrderType = OrderType.MARKET
    
    # NEW fields from Phase C
    pyramid_level:       int   = 1
    slippage_applied:    float = 0.0
    sl_spec:             StopLossSpec = field(default_factory=StopLossSpec)
    tp_spec:             TakeProfitSpec = field(default_factory=TakeProfitSpec)
    target_price:        Optional[float] = None
    partial_exit_done:   bool = False
    time_exit_bar:       Optional[int] = None
    gtt_order:           Optional[GTTOrder] = None

    # ------------------------------------------------------------------
    def unrealised_pnl(self, current_price: float) -> float:
        """Mark-to-market unrealised profit/loss at ``current_price``."""
        return (current_price - self.entry_price) * self.direction * self.quantity

    def update_excursion(self, price: float) -> None:
        """Update MAE / MFE with the latest price."""
        move = (price - self.entry_price) * self.direction
        self.mfe = max(self.mfe, move)
        self.mae = min(self.mae, move)

    def update_chandelier_stop(self, high_series: np.ndarray, low_series: np.ndarray, atr: float, bar_idx: int) -> None:
        """Update trailing stop using Chandelier logic."""
        if not self.sl_spec or not self.sl_spec.is_active() or self.sl_spec.sl_type.name != "CHANDELIER":
            return
        if atr is None or atr <= 0:
            return
            
        period = self.sl_spec.chandelier_period
        start_idx = max(0, bar_idx - period)
        
        if self.direction == 1:
            highest_high = np.max(high_series[start_idx:bar_idx+1])
            ideal = highest_high - (self.sl_spec.value * atr)
            if self.trailing_stop_level == 0.0:
                self.trailing_stop_level = self.entry_price - (self.sl_spec.value * atr)
            self.trailing_stop_level = max(self.trailing_stop_level, ideal)
        else:
            lowest_low = np.min(low_series[start_idx:bar_idx+1])
            ideal = lowest_low + (self.sl_spec.value * atr)
            if self.trailing_stop_level == 0.0:
                self.trailing_stop_level = self.entry_price + (self.sl_spec.value * atr)
            self.trailing_stop_level = min(self.trailing_stop_level, ideal)

    def update_trailing_stop(self, high: float, low: float, atr: Optional[float] = None, period_high: Optional[float] = None) -> None:
        """
        Advance the trailing stop level if price moved in our favour.

        The stop NEVER moves against the trade.
        """
        if self.sl_spec.is_active() and self.sl_spec.is_trailing():
            if self.sl_spec.sl_type == StopLossType.TRAILING_PCT:
                dist = self.entry_price * (self.sl_spec.value / 100.0)
            elif self.sl_spec.sl_type == StopLossType.TRAILING_POINTS:
                dist = self.sl_spec.value
            elif self.sl_spec.sl_type == StopLossType.TRAILING_TICKS:
                dist = self.sl_spec.value * self.sl_spec.tick_size
            elif self.sl_spec.sl_type == StopLossType.TRAILING_ATR:
                if atr is None:
                    return
                dist = self.sl_spec.value * atr
            elif self.sl_spec.sl_type == StopLossType.CHANDELIER:
                if atr is None or period_high is None:
                    return
                dist = self.sl_spec.value * atr
            else:
                dist = 0.0
        else:
            if self.trailing_stop_pct > 0:
                dist = self.entry_price * (self.trailing_stop_pct / 100.0)
            elif self.trailing_stop_amt > 0:
                dist = self.trailing_stop_amt
            else:
                return   # no trailing stop configured

        if self.direction == 1:   # LONG — trail behind high
            if self.sl_spec.is_active() and self.sl_spec.sl_type == StopLossType.CHANDELIER:
                ideal = period_high - dist
            else:
                ideal = high - dist
                
            if self.trailing_stop_level == 0.0:
                if self.sl_spec.is_active() and self.sl_spec.sl_type == StopLossType.CHANDELIER:
                    self.trailing_stop_level = self.entry_price - dist
                else:
                    self.trailing_stop_level = self.entry_price - dist
            self.trailing_stop_level = max(self.trailing_stop_level, ideal)
        else:                     # SHORT — trail above low
            if self.sl_spec.is_active() and self.sl_spec.sl_type == StopLossType.CHANDELIER:
                ideal = period_high + dist
            else:
                ideal = low + dist
                
            if self.trailing_stop_level == 0.0:
                if self.sl_spec.is_active() and self.sl_spec.sl_type == StopLossType.CHANDELIER:
                    self.trailing_stop_level = self.entry_price + dist
                else:
                    self.trailing_stop_level = self.entry_price + dist
            self.trailing_stop_level = min(self.trailing_stop_level, ideal)

    def is_trailing_stop_triggered(self, open_p: float, low: float, high: float):
        """
        Returns ``(triggered: bool, fill_price: float)``.

        Fills at ``open_p`` when price gaps through the stop, otherwise at
        the stop level.
        """
        if self.trailing_stop_level == 0.0:
            return False, 0.0
        if self.direction == 1:   # LONG exit if low < stop
            if open_p <= self.trailing_stop_level:
                return True, open_p    # gap-through — fill at open
            if low <= self.trailing_stop_level:
                return True, self.trailing_stop_level
        else:                     # SHORT exit if high > stop
            if open_p >= self.trailing_stop_level:
                return True, open_p
            if high >= self.trailing_stop_level:
                return True, self.trailing_stop_level
        return False, 0.0

    def is_fixed_stop_triggered(self, open_p: float, low: float, high: float):
        """Returns ``(triggered: bool, fill_price: float)`` for fixed stop."""
        if self.stop_price is None:
            return False, 0.0
        if self.direction == 1:
            if open_p <= self.stop_price:
                return True, open_p
            if low <= self.stop_price:
                return True, self.stop_price
        else:
            if open_p >= self.stop_price:
                return True, open_p
            if high >= self.stop_price:
                return True, self.stop_price
        return False, 0.0

    def is_target_triggered(self, open_p: float, low: float, high: float) -> tuple[bool, float]:
        """Returns ``(triggered: bool, fill_price: float)`` for take profit."""
        if self.target_price is None:
            return False, 0.0
        if self.direction == 1:
            if open_p >= self.target_price:
                return True, open_p
            if high >= self.target_price:
                return True, self.target_price
        else:
            if open_p <= self.target_price:
                return True, open_p
            if low <= self.target_price:
                return True, self.target_price
        return False, 0.0

    def is_time_exit_due(self, current_bar_idx: int) -> bool:
        """Returns True if the time-based exit bar has been reached."""
        if self.time_exit_bar is not None and current_bar_idx >= self.time_exit_bar:
            return True
        return False

    @property
    def direction_label(self) -> str:
        return "LONG" if self.direction == 1 else "SHORT"


# ---------------------------------------------------------------------------
# Trade  (one completed round-trip)
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """
    Represents one completed round-trip trade.

    Created by :class:`backtester.fill_engine.FillEngine` when an exit fills,
    by closing the matching :class:`Position`.

    All monetary values are in ₹.

    Attributes
    ----------
    symbol : str
    entry_time, exit_time : pd.Timestamp
    entry_price, exit_price : float
    quantity : int
    direction : int  (+1 LONG / -1 SHORT)
    direction_label : str  ("LONG" / "SHORT")
    gross_pnl : float
        (exit_price - entry_price) × qty × direction — before costs.
    entry_charges, exit_charges, total_charges : float
    net_pnl : float
        gross_pnl − total_charges.
    pnl_pct : float
        net_pnl / (entry_price × qty).
    entry_signal, exit_signal : str
    duration : str
        Human-readable duration (e.g. ``"3d 2h 15m"``).
    duration_bars : int
    mae, mfe : float
        Maximum adverse / favourable excursion in ₹.
    cumulative_portfolio : float
        Total portfolio value immediately after this trade closes.
    """
    symbol:               str
    entry_time:           pd.Timestamp
    exit_time:            pd.Timestamp
    entry_price:          float
    exit_price:           float
    quantity:             int
    direction:            int
    direction_label:      str
    gross_pnl:            float
    entry_charges:        float
    exit_charges:         float
    total_charges:        float
    net_pnl:              float
    pnl_pct:              float
    entry_signal:         str   = ""
    exit_signal:          str   = ""
    duration:             str   = ""
    duration_bars:        int   = 0
    mae:                  float = 0.0
    mfe:                  float = 0.0
    cumulative_portfolio: float = 0.0
    pyramid_level:        int   = 1
    slippage:             float = 0.0
    tag:                  str   = ""
    sl_type:              str   = ""
    tp_type:              str   = ""
    exit_reason:          str   = ""
    partial:              bool  = False

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict (used for CSV export)."""
        return {
            "symbol":           self.symbol,
            "entry_time":       str(self.entry_time),
            "exit_time":        str(self.exit_time),
            "direction":        self.direction_label,
            "entry_price":      round(self.entry_price,  2),
            "exit_price":       round(self.exit_price,   2),
            "quantity":         self.quantity,
            "gross_pnl":        round(self.gross_pnl,    2),
            "entry_charges":    round(self.entry_charges, 2),
            "exit_charges":     round(self.exit_charges,  2),
            "total_charges":    round(self.total_charges, 2),
            "net_pnl":          round(self.net_pnl,       2),
            "pnl_pct":          round(self.pnl_pct,       4),
            "entry_signal":     self.entry_signal,
            "exit_signal":      self.exit_signal,
            "duration":         self.duration,
            "duration_bars":    self.duration_bars,
            "mae":              round(self.mae * self.quantity, 2),
            "mfe":              round(self.mfe * self.quantity, 2),
            "portfolio_value":  round(self.cumulative_portfolio, 2),
        }


# ---------------------------------------------------------------------------
# BacktestResult  (engine output container)
# ---------------------------------------------------------------------------

class BacktestResult:
    """
    Container returned by :meth:`backtester.engine.BacktestEngine.run`.

    Do not construct manually — the engine builds this for you.

    Attributes
    ----------
    config : BacktestConfig
    symbol : str
    trade_log : list[Trade]
    equity_curve : pd.Series
        Portfolio value at each bar (float64, same index as signals_df).
    drawdown : pd.Series
        Drawdown from peak at each bar, expressed as a negative fraction
        (e.g. −0.15 = 15 % below peak).
    signals_df : pd.DataFrame
        The DataFrame returned by the strategy, containing OHLCV columns,
        indicator columns, and the ``signal`` column.
    """

    def __init__(
        self,
        config:       BacktestConfig,
        symbol:       str,
        trade_log:    List[Trade],
        equity_curve: pd.Series,
        drawdown:     pd.Series,
        signals_df:   pd.DataFrame,
        run_id:       str = "",
        strategy_name: str = "",
        created_at:   str = "",
    ) -> None:
        self.config       = config
        self.symbol       = symbol
        self.trade_log    = trade_log
        self.equity_curve = equity_curve
        self.drawdown     = drawdown
        self.signals_df   = signals_df
        self.run_id       = run_id
        self.strategy_name = strategy_name
        self.created_at   = created_at
        self._metrics: Optional[Dict] = None   # lazy-computed

    # ------------------------------------------------------------------
    def trade_df(self) -> pd.DataFrame:
        """Return all trades as a DataFrame (one row per trade)."""
        if not self.trade_log:
            return pd.DataFrame()
        return pd.DataFrame([t.to_dict() for t in self.trade_log])

    def metrics(self) -> Dict:
        """
        Return the full performance metrics dict.

        Computed lazily and cached — subsequent calls are O(1).
        """
        if self._metrics is None:
            from backtester.performance import compute_performance
            self._metrics = compute_performance(
                trade_log    = self.trade_log,
                equity_curve = self.equity_curve,
                config       = self.config,
            )
        return self._metrics

    def summary(self) -> str:
        """Return a formatted text summary of performance metrics."""
        m = self.metrics()
        if "error" in m:
            return f"Backtest — {self.symbol} — {m['error']}"
        width = 55
        lines = [
            "", "=" * width,
            f"  BACKTEST RESULTS — {self.symbol}",
            "=" * width,
        ]
        order = [
            ("Start Date",             "start_date"),
            ("End Date",               "end_date"),
            ("Initial Capital",        "initial_capital"),
            ("Final Capital",          "final_capital"),
            ("Total Net P&L",          "total_net_pnl"),
            ("Total Return",           "total_return_pct"),
            ("CAGR",                   "cagr_pct"),
            ("Sharpe Ratio",           "sharpe_ratio"),
            ("Sortino Ratio",          "sortino_ratio"),
            ("Calmar Ratio",           "calmar_ratio"),
            ("Max Drawdown",           "max_drawdown_pct"),
            ("Total Trades",           "total_trades"),
            ("Win Rate",               "win_rate_pct"),
            ("Profit Factor",          "profit_factor"),
            ("Expectancy / Trade",     "expectancy_inr"),
            ("Avg Win",                "avg_win_inr"),
            ("Avg Loss",               "avg_loss_inr"),
            ("Max Consec. Wins",       "max_consecutive_wins"),
            ("Max Consec. Losses",     "max_consecutive_losses"),
            ("Exposure %",             "exposure_pct"),
            ("Total Commission Paid",  "total_commission_paid"),
        ]
        for label, key in order:
            val = m.get(key, "N/A")
            if isinstance(val, float):
                if key in ("total_return_pct", "cagr_pct", "win_rate_pct",
                           "max_drawdown_pct", "exposure_pct"):
                    val = f"{val:.2f}%"
                elif key in ("sharpe_ratio", "sortino_ratio", "calmar_ratio", "profit_factor"):
                    val = f"{val:.3f}"
                else:
                    val = f"₹{val:,.2f}"
            lines.append(f"  {label:<26}: {val}")
        lines.append("=" * width)
        return "\n".join(lines)

    def export_signals_csv(self, path: str) -> None:
        """Write OHLCV + indicators + signal column to a CSV file."""
        if self.signals_df is None or self.signals_df.empty:
            raise ValueError("No signal data available.")
        self.signals_df.to_csv(path)

    def to_dict(self) -> Dict[str, object]:
        """Serialize the result at a summary level for APIs or tests."""
        return {
            "symbol": self.symbol,
            "config": {
                "initial_capital": self.config.initial_capital,
                "segment": self.config.segment.value,
                "allow_shorting": self.config.allow_shorting,
                "default_order_type": self.config.default_order_type.value,
            },
            "metrics": self.metrics(),
            "trade_count": len(self.trade_log),
        }

    def export(self, output_dir: str | Path, formats: List[str] = None) -> List[Path]:
        """Export backtest results using BacktestExporter."""
        from backtester.exporter import BacktestExporter
        exporter = BacktestExporter(self, output_dir)
        return exporter.export(formats)


# ---------------------------------------------------------------------------
# PortfolioResult (multi-symbol output container)
# ---------------------------------------------------------------------------

@dataclass
class PortfolioResult:
    """
    Container returned by PortfolioManager or backtesting multiple symbols.
    """
    run_id: str
    strategy_name: str
    created_at: str
    config: BacktestConfig
    symbol_results: Dict[str, BacktestResult]  # per-symbol
    combined_equity_curve: pd.Series           # shared capital equity
    combined_drawdown: pd.Series
    combined_trade_log: List[Trade]            # all trades merged

    def metrics(self) -> Dict:
        """Return combined metrics dict."""
        from backtester.performance import compute_performance
        return compute_performance(
            trade_log=self.combined_trade_log,
            equity_curve=self.combined_equity_curve,
            config=self.config
        )

    def summary(self) -> str:
        """Return a formatted text summary for the portfolio."""
        m = self.metrics()
        width = 55
        lines = [
            "", "=" * width,
            f"  PORTFOLIO RESULTS — {len(self.symbol_results)} Symbols",
            "=" * width,
        ]
        order = [
            ("Start Date",             "start_date"),
            ("End Date",               "end_date"),
            ("Initial Capital",        "initial_capital"),
            ("Final Capital",          "final_capital"),
            ("Total Net P&L",          "total_net_pnl"),
            ("Total Return",           "total_return_pct"),
            ("CAGR",                   "cagr_pct"),
            ("Sharpe Ratio",           "sharpe_ratio"),
            ("Sortino Ratio",          "sortino_ratio"),
            ("Max Drawdown",           "max_drawdown_pct"),
            ("Total Trades",           "total_trades"),
            ("Win Rate",               "win_rate_pct"),
        ]
        for label, key in order:
            val = m.get(key, "N/A")
            if isinstance(val, float):
                if key in ("total_return_pct", "cagr_pct", "win_rate_pct", "max_drawdown_pct"):
                    val = f"{val:.2f}%"
                elif key in ("sharpe_ratio", "sortino_ratio"):
                    val = f"{val:.3f}"
                else:
                    val = f"₹{val:,.2f}"
            lines.append(f"  {label:<26}: {val}")
        lines.append("=" * width)
        return "\n".join(lines)

    def export(self, output_dir: str | Path, formats: List[str] = None) -> List[Path]:
        """Export portfolio results using BacktestExporter."""
        from backtester.exporter import BacktestExporter
        exporter = BacktestExporter(self, output_dir)
        return exporter.export(formats)