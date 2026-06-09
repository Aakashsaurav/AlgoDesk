"""
indicators/helpers.py
---------------------
Signal and candlestick helper utilities.
"""

from __future__ import annotations

import pandas as pd


def crossover(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """True on the bar where series1 crosses above series2."""
    return (series1 > series2) & (series1.shift(1) <= series2.shift(1))


def crossunder(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """True on the bar where series1 crosses below series2."""
    return (series1 < series2) & (series1.shift(1) >= series2.shift(1))


def above_threshold(series: pd.Series, level: float) -> pd.Series:
    """True on the bar where series crosses above a scalar threshold."""
    return (series > level) & (series.shift(1) <= level)


def below_threshold(series: pd.Series, level: float) -> pd.Series:
    """True on the bar where series crosses below a scalar threshold."""
    return (series < level) & (series.shift(1) >= level)


def candle_body(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Absolute candle body size."""
    return (close - open_).abs()


def candle_range(high: pd.Series, low: pd.Series) -> pd.Series:
    """Full candle range."""
    return high - low


def is_green(open_: pd.Series, close: pd.Series) -> pd.Series:
    """True for bullish candles."""
    return close > open_


def is_red(open_: pd.Series, close: pd.Series) -> pd.Series:
    """True for bearish candles."""
    return close < open_


def upper_shadow(open_: pd.Series, high: pd.Series, close: pd.Series) -> pd.Series:
    """Upper wick length."""
    return high - pd.concat([open_, close], axis=1).max(axis=1)


def lower_shadow(open_: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Lower wick length."""
    return pd.concat([open_, close], axis=1).min(axis=1) - low


__all__ = [
    "crossover",
    "crossunder",
    "above_threshold",
    "below_threshold",
    "candle_body",
    "candle_range",
    "is_green",
    "is_red",
    "upper_shadow",
    "lower_shadow",
]
