"""
strategies/day_strategy/orb_nifty.py
======================================
Opening Range Breakout (ORB)
Institutional-grade intraday strategy module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time as dtime
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from strategies.categories import StrategyCategory
from strategies.utils import require_datetime_index

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Module-level constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OR_START_TIME = dtime(9, 15)
SIGNAL_START = dtime(9, 30)
SQUAREOFF_TIME = dtime(15, 15)
MARKET_CLOSE = dtime(15, 30)

MIN_OR_BARS = 10
TRAILING_DIVISOR = 5.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pure data containers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class ORLevels:
    date: str
    or_high: float
    or_low: float
    is_valid: bool = True
    bar_count: int = 0

    def __repr__(self) -> str:
        return (
            f"ORLevels(date={self.date!r}, "
            f"high={self.or_high:.2f}, low={self.or_low:.2f}, "
            f"valid={self.is_valid}, bars={self.bar_count})"
        )

@dataclass
class DayTradeState:
    date: str
    long_taken: bool = False
    short_taken: bool = False

    @property
    def both_legs_used(self) -> bool:
        return self.long_taken and self.short_taken

@dataclass
class SignalBar:
    timestamp: pd.Timestamp
    bar_index: int
    direction: int
    stop_loss: float
    signal_tag: str

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sub-component 1: Indicator computation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ORBIndicators:
    @staticmethod
    def compute_or_levels(df: pd.DataFrame, or_end_time: dtime) -> Dict[str, ORLevels]:
        result: Dict[str, ORLevels] = {}

        bar_times = df.index.time
        bar_dates = df.index.date

        for dt in np.unique(bar_dates):
            date_str = str(dt)

            day_mask = bar_dates == dt
            or_mask = (bar_times >= OR_START_TIME) & (bar_times <= or_end_time)
            or_bars = df.iloc[day_mask & or_mask]

            if len(or_bars) < MIN_OR_BARS:
                result[date_str] = ORLevels(
                    date=date_str,
                    or_high=float("nan"),
                    or_low=float("nan"),
                    is_valid=False,
                    bar_count=len(or_bars),
                )
                logger.debug(
                    "ORB %s: only %d OR bars (need %d) — day skipped",
                    date_str, len(or_bars), MIN_OR_BARS
                )
                continue

            result[date_str] = ORLevels(
                date=date_str,
                or_high=float(or_bars["high"].max()),
                or_low=float(or_bars["low"].min()),
                is_valid=True,
                bar_count=len(or_bars),
            )

        valid_count = sum(1 for v in result.values() if v.is_valid)
        logger.info(
            "ORBIndicators: %d days processed, %d valid OR days",
            len(result), valid_count
        )
        return result

    @staticmethod
    def compute_vwap(df: pd.DataFrame) -> pd.Series:
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        tp_vol = typical * df["volume"]
        bar_dates = pd.Series(df.index.date, index=df.index)

        cum_tp_vol = tp_vol.groupby(bar_dates).cumsum()
        cum_vol = df["volume"].groupby(bar_dates).cumsum()

        vwap = (cum_tp_vol / cum_vol.replace(0, np.nan)).rename("vwap")
        return vwap

    @staticmethod
    def broadcast_or_levels(
        df: pd.DataFrame,
        or_levels: Dict[str, ORLevels],
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        n = len(df)
        bar_dates = df.index.date
        high_arr = np.full(n, np.nan, dtype=float)
        low_arr = np.full(n, np.nan, dtype=float)
        valid_arr = np.zeros(n, dtype=bool)

        for i, dt in enumerate(bar_dates):
            lvl = or_levels.get(str(dt))
            if lvl and lvl.is_valid:
                high_arr[i] = lvl.or_high
                low_arr[i] = lvl.or_low
                valid_arr[i] = True

        return (
            pd.Series(high_arr, index=df.index, name="or_high"),
            pd.Series(low_arr, index=df.index, name="or_low"),
            pd.Series(valid_arr, index=df.index, name="or_valid"),
        )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sub-component 2: Trailing stop increment
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ORBTrailingStop:
    @staticmethod
    def compute_increment(df: pd.DataFrame, divisor: float = TRAILING_DIVISOR) -> pd.Series:
        prev_body = (df["open"] - df["close"]).abs().shift(1)
        increment = (prev_body / divisor).fillna(0.0)
        return increment.rename("trail_increment")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main strategy class
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class OpeningRangeBreakoutStrategy(BaseStrategy):
    PARAM_SCHEMA = [
        {"name": "or_window_minutes", "type": "int", "default": 15, "min": 5, "max": 120, "step": 5, "label": "OR Window", "description": "Opening range window in minutes.", "unit": "min", "optimize": True},
        {"name": "vwap_filter", "type": "bool", "default": True, "label": "VWAP Filter", "description": "Require close > VWAP for longs and < VWAP for shorts.", "optimize": True},
        {"name": "trailing_divisor", "type": "float", "default": 5.0, "min": 1.0, "max": 10.0, "step": 0.5, "label": "Trailing Divisor", "description": "Divisor for trailing stop loss.", "optimize": True},
        {"name": "min_body_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 2.0, "step": 0.1, "label": "Min Body %", "description": "Minimum body percentage for valid breakout candle.", "optimize": True},
        {"name": "position_mode", "type": "select", "default": "long_short", "options": ["long_short", "long_only", "short_only"], "label": "Position Mode", "description": "Allowed directions.", "optimize": False},
    ]
    DESCRIPTION = (
        "Opening Range Breakout (ORB) — Long on green candle crossing OR_high + VWAP; "
        "Short on red candle crossing OR_low + below VWAP. "
        "Max 1 trade per leg per day. Hard squareoff at 15:15 IST."
    )
    CATEGORY = StrategyCategory.BREAKOUT.value

    def __init__(
        self,
        or_window_minutes: int = 15,
        vwap_filter: bool = True,
        trailing_divisor: float = 5.0,
        min_body_pct: float = 0.0,
        position_mode: str = "long_short",
    ) -> None:
        self.or_window_minutes = int(or_window_minutes)
        self.vwap_filter = bool(vwap_filter)
        self.trailing_divisor = float(trailing_divisor)
        self.min_body_pct = float(min_body_pct)
        self.position_mode = str(position_mode)

        super().__init__(
            name="Opening Range Breakout",
            description=self.DESCRIPTION,
            params={
                "or_window_minutes": self.or_window_minutes,
                "vwap_filter": self.vwap_filter,
                "trailing_divisor": self.trailing_divisor,
                "min_body_pct": self.min_body_pct,
                "position_mode": self.position_mode,
            },
        )

        end_minute = 14 + self.or_window_minutes
        end_hour = 9 + end_minute // 60
        end_minute = end_minute % 60
        self._or_end_time = dtime(end_hour, end_minute)

    @property
    def warmup_period(self) -> int:
        return max(MIN_OR_BARS, self.or_window_minutes)

    def validate_params(self) -> None:
        super().validate_params()
        if self.or_window_minutes < 5 or self.or_window_minutes > 120:
            raise ValueError("or_window_minutes must be between 5 and 120.")
        if self.trailing_divisor <= 0:
            raise ValueError("trailing_divisor must be > 0.")
        if self.min_body_pct < 0:
            raise ValueError("min_body_pct must be >= 0.")
        if self.position_mode not in ("long_short", "long_only", "short_only"):
            raise ValueError("Invalid position_mode.")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)
        require_datetime_index(df, self.name)
        
        # Make sure df is explicitly copied after base validation if we are going to use iterrows/assigning directly
        df = df.copy()

        ind = ORBIndicators()
        or_lvls = ind.compute_or_levels(df, self._or_end_time)
        or_h, or_l, or_v = ind.broadcast_or_levels(df, or_lvls)

        df["or_high"] = or_h
        df["or_low"] = or_l
        df["or_valid"] = or_v

        df["vwap"] = ind.compute_vwap(df)
        df["trail_increment"] = ORBTrailingStop.compute_increment(df, divisor=self.trailing_divisor)

        bar_times = df.index.time
        
        # Derive dynamically when signals can start (right after OR window)
        sig_start_min = 15 + self.or_window_minutes
        sig_start_hr = 9 + sig_start_min // 60
        sig_start_min = sig_start_min % 60
        dynamic_signal_start = dtime(sig_start_hr, sig_start_min)
        
        after_or_window = pd.Series(bar_times, index=df.index) >= dynamic_signal_start
        before_squareoff = pd.Series(bar_times, index=df.index) < SQUAREOFF_TIME
        tradeable = after_or_window & before_squareoff

        is_green = df["close"] > df["open"]
        is_red = df["close"] < df["open"]

        if self.min_body_pct > 0:
            body = (df["close"] - df["open"]).abs()
            min_body = df["close"] * (self.min_body_pct / 100.0)
            is_green = is_green & (body >= min_body)
            is_red = is_red & (body >= min_body)

        long_break = tradeable & df["or_valid"] & is_green & (df["close"] > df["or_high"])
        short_break = tradeable & df["or_valid"] & is_red & (df["close"] < df["or_low"])

        if self.vwap_filter:
            long_break = long_break & (df["close"] > df["vwap"])
            short_break = short_break & (df["close"] < df["vwap"])

        df["stop_loss"] = np.nan
        df["signal_sl"] = np.nan  # Alias for compatibility
        df["signal_tag"] = ""
        df["signal"] = 0

        self._apply_daily_limits(df, long_break, short_break)

        n_long = (df["signal"] == 1).sum()
        n_short = (df["signal"] == -1).sum()
        n_days = len(np.unique(df.index.date))
        
        logger.info(
            "OpeningRangeBreakoutStrategy: %d bars | %d days | LONG signals=%d | SHORT signals=%d | vwap_filter=%s | OR window=%dmin",
            len(df), n_days, n_long, n_short, self.vwap_filter, self.or_window_minutes
        )

        return self._finalize_signals(df)

    def _apply_daily_limits(
        self,
        df: pd.DataFrame,
        long_break: pd.Series,
        short_break: pd.Series,
    ) -> None:
        bar_dates = df.index.date

        for dt in np.unique(bar_dates):
            day_mask = bar_dates == dt
            day_idx = df.index[day_mask]

            state = DayTradeState(date=str(dt))

            for ts in day_idx:
                if state.both_legs_used:
                    break

                is_long_sig = bool(long_break.loc[ts]) if not state.long_taken and self.position_mode != "short_only" else False
                is_short_sig = bool(short_break.loc[ts]) if not state.short_taken and self.position_mode != "long_only" else False

                if is_long_sig:
                    df.at[ts, "signal"] = 1
                    sl_val = float(df.at[ts, "open"])
                    df.at[ts, "stop_loss"] = sl_val
                    df.at[ts, "signal_sl"] = sl_val
                    df.at[ts, "signal_tag"] = "ORB_LONG"
                    
                    from strategies.utils import build_order_spec
                    df.at[ts, "order_spec"] = build_order_spec(
                        direction=1,
                        order_type_str="MARKET",
                        sl_type_str="FIXED_PRICE",
                        sl_value=sl_val
                    )
                    
                    state.long_taken = True
                    logger.debug(
                        "ORB LONG signal: %s | close=%.2f > or_high=%.2f | SL=%.2f",
                        ts, df.at[ts, 'close'], df.at[ts, 'or_high'], sl_val
                    )

                elif is_short_sig:
                    df.at[ts, "signal"] = -1
                    sl_val = float(df.at[ts, "open"])
                    df.at[ts, "stop_loss"] = sl_val
                    df.at[ts, "signal_sl"] = sl_val
                    df.at[ts, "signal_tag"] = "ORB_SHORT"
                    
                    from strategies.utils import build_order_spec
                    df.at[ts, "order_spec"] = build_order_spec(
                        direction=-1,
                        order_type_str="MARKET",
                        sl_type_str="FIXED_PRICE",
                        sl_value=sl_val
                    )

                    state.short_taken = True
                    logger.debug(
                        "ORB SHORT signal: %s | close=%.2f < or_low=%.2f | SL=%.2f",
                        ts, df.at[ts, 'close'], df.at[ts, 'or_low'], sl_val
                    )

# Alias for backward compatibility
class ORBNiftyStrategy(OpeningRangeBreakoutStrategy):
    pass

__all__ = [
    "OpeningRangeBreakoutStrategy",
    "ORBNiftyStrategy",
    "ORBIndicators",
    "ORBTrailingStop",
    "ORLevels",
    "DayTradeState",
    "SignalBar",
    "OR_START_TIME",
    "SIGNAL_START",
    "SQUAREOFF_TIME",
    "TRAILING_DIVISOR",
    "MIN_OR_BARS",
]
