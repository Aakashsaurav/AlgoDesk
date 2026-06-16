"""
strategies/utils.py
-------------------
Utility functions for strategies. Centralizes repeated signal-cleaning logic,
time/session helpers, and output formatting.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── G1. State Machine Helpers ─────────────────────────────────────────────────

def long_only_state_signals(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """
    Convert raw boolean entry/exit masks into stateful signals (1 for entry, -1 for exit).
    Prevents duplicate entry signals when already long.
    """
    signal_arr = np.zeros(len(entry), dtype=int)
    in_trade = False

    entry_vals = entry.values
    exit_vals = exit_.values

    for i in range(len(entry)):
        if not in_trade:
            if entry_vals[i]:
                signal_arr[i] = 1
                in_trade = True
        else:
            if exit_vals[i]:
                signal_arr[i] = -1
                in_trade = False

    return pd.Series(signal_arr, index=entry.index)


def long_short_state_signals(
    long_entry: pd.Series,
    short_entry: pd.Series,
    exit_long: Optional[pd.Series] = None,
    exit_short: Optional[pd.Series] = None
) -> pd.Series:
    """
    Convert raw boolean entry/exit masks into stateful signals for long/short.
    1 for long entry, -1 for short entry, 0 otherwise.
    (If already long, we must exit before going short, or we can reverse).
    """
    signal_arr = np.zeros(len(long_entry), dtype=int)
    current_position = 0  # 1 for long, -1 for short, 0 for flat

    le_vals = long_entry.values
    se_vals = short_entry.values
    
    xl_vals = exit_long.values if exit_long is not None else np.zeros(len(long_entry), dtype=bool)
    xs_vals = exit_short.values if exit_short is not None else np.zeros(len(long_entry), dtype=bool)

    for i in range(len(long_entry)):
        if current_position == 0:
            if le_vals[i]:
                signal_arr[i] = 1
                current_position = 1
            elif se_vals[i]:
                signal_arr[i] = -1
                current_position = -1
        elif current_position == 1:
            if xl_vals[i] or se_vals[i]:  # Exit long or reverse to short
                signal_arr[i] = -1
                current_position = -1 if se_vals[i] else 0
        elif current_position == -1:
            if xs_vals[i] or le_vals[i]:  # Exit short or reverse to long
                signal_arr[i] = 1
                current_position = 1 if le_vals[i] else 0

    return pd.Series(signal_arr, index=long_entry.index)


def suppress_warmup(df: pd.DataFrame, warmup_bars: int, columns: Tuple[str, ...] = ("signal", "signal_tag")) -> pd.DataFrame:
    """
    Suppress signal columns during the warmup period (first `warmup_bars` rows).
    """
    if warmup_bars <= 0 or len(df) == 0:
        return df

    idx = min(warmup_bars, len(df))
    if "signal" in columns and "signal" in df.columns:
        df.loc[df.index[:idx], "signal"] = 0
    if "signal_tag" in columns and "signal_tag" in df.columns:
        df.loc[df.index[:idx], "signal_tag"] = ""

    return df


def first_signal_per_session(df: pd.DataFrame, signal_mask: pd.Series, session_index: pd.Series) -> pd.Series:
    """
    Return a boolean series that is True only for the first True value in `signal_mask`
    for each unique session in `session_index`.
    """
    temp_df = pd.DataFrame({'signal': signal_mask, 'session': session_index}, index=df.index)
    true_signals = temp_df[temp_df['signal']]
    first_true_indices = true_signals.groupby('session').head(1).index
    
    out_mask = pd.Series(False, index=df.index)
    out_mask.loc[first_true_indices] = True
    return out_mask


# ── G2. Time/Session Helpers ──────────────────────────────────────────────────

def require_datetime_index(df: pd.DataFrame, strategy_name: str) -> None:
    """
    Ensure the DataFrame has a DatetimeIndex. Raises ValueError otherwise.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"Strategy '{strategy_name}' requires a DatetimeIndex. "
            f"Got {type(df.index).__name__} instead."
        )


def session_dates(index: pd.DatetimeIndex) -> np.ndarray:
    """
    Extract just the dates (as strings or pandas dates) from a DatetimeIndex.
    """
    return index.date


def time_mask(index: pd.DatetimeIndex, start_time: str, end_time: str, inclusive: bool = True) -> np.ndarray:
    """
    Return a boolean numpy array indicating if the index's time is between start_time and end_time.
    Format for times should be 'HH:MM' or 'HH:MM:SS'.
    """
    start_t = pd.to_datetime(start_time).time()
    end_t = pd.to_datetime(end_time).time()
    times = index.time
    
    if inclusive:
        return (times >= start_t) & (times <= end_t)
    else:
        return (times > start_t) & (times < end_t)


# ── G3. Output Helpers ────────────────────────────────────────────────────────

def set_signal(df: pd.DataFrame, mask: pd.Series, value: int, tag: str, reason: str = "") -> None:
    """
    Set `signal` and `signal_tag` columns in df where `mask` is True.
    """
    if "signal" not in df.columns:
        df["signal"] = 0
    if "signal_tag" not in df.columns:
        df["signal_tag"] = ""

    df.loc[mask, "signal"] = value
    
    if reason:
        tag = f"{tag}_{reason}"
    df.loc[mask, "signal_tag"] = tag


def copy_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a clean copy of the base OHLCV columns.
    """
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[cols].copy()


def validate_no_lookahead_columns(df: pd.DataFrame) -> None:
    """
    Placeholder for future audit rules. Raises an error if known future columns exist.
    """
    forbidden = {"next_open", "next_close", "future_return", "target"}
    found = forbidden.intersection(df.columns)
    if found:
        raise ValueError(f"Look-ahead columns detected in DataFrame: {found}")


def build_order_spec(
    direction: int,
    order_type_str: str = "MARKET",
    sl_type_str: str = "NONE",
    sl_value: float = 0.0,
    tp_type_str: str = "NONE",
    tp_value: float = 0.0,
) -> Optional[Any]:
    """
    Safely build a backtester OrderSpec if the backtester package is available.
    """
    try:
        from backtester.orders import OrderSpec, OrderType, StopLossSpec, StopLossType, TakeProfitSpec, TakeProfitType
    except ImportError:
        return None

    try:
        otype = OrderType[order_type_str.upper()]
        sl_type = StopLossType[sl_type_str.upper()]
        tp_type = TakeProfitType[tp_type_str.upper()]
    except KeyError:
        return None

    sl_spec = StopLossSpec(sl_type=sl_type, value=sl_value) if sl_type != StopLossType.NONE else StopLossSpec()
    tp_spec = TakeProfitSpec(tp_type=tp_type, value=tp_value) if tp_type != TakeProfitType.NONE else TakeProfitSpec()

    return OrderSpec(
        direction=direction,
        order_type=otype,
        sl_spec=sl_spec,
        tp_spec=tp_spec,
    )
