"""
indicators/technical.py
------------------------
Backward-compatible compatibility layer for legacy imports.

Canonical implementations live in the modular indicator files:
`moving_averages.py`, `oscillators.py`, `volatility.py`, `trend.py`,
`statistics.py`, `volume.py`, and `helpers.py`.
"""

from __future__ import annotations

import warnings
import pandas as pd

warnings.warn(
    "The `indicators.technical` module is deprecated and will be removed in Phase 3. "
    "Please import indicators directly from their respective modules "
    "(e.g., `from indicators.moving_averages import sma`).",
    DeprecationWarning,
    stacklevel=2,
)

from indicators.helpers import (
    above_threshold,
    below_threshold,
    candle_body as _candle_body,
    candle_range as _candle_range,
    crossover,
    crossunder,
    is_green as _is_green,
    is_red as _is_red,
    lower_shadow as _lower_shadow,
    upper_shadow as _upper_shadow,
)
from indicators.moving_averages import dema, ema, sma, vwap as _series_vwap, wma
from indicators.oscillators import cci, macd as _series_macd, roc, rsi, stochastic as _series_stochastic
from indicators.statistics import rolling_correlation, zscore
from indicators.trend import adx, supertrend as _series_supertrend
from indicators.volatility import atr as _series_atr, bollinger_bands, keltner_channels as _series_keltner_channels
from indicators.volume import obv as _series_obv


def atr(df: pd.DataFrame, period: int = 14):
    """Compatibility wrapper around `indicators.volatility.atr`."""
    return _series_atr(df["high"], df["low"], df["close"], period)


def macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
):
    """Compatibility wrapper around `indicators.oscillators.macd`."""
    return _series_macd(series, fast_period, slow_period, signal_period)


def supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
):
    """Compatibility wrapper around `indicators.trend.supertrend`."""
    return _series_supertrend(df["high"], df["low"], df["close"], period, multiplier)


def stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
):
    """Compatibility wrapper around `indicators.oscillators.stochastic`."""
    return _series_stochastic(df["high"], df["low"], df["close"], k_period, d_period)


def keltner_channels(
    df: pd.DataFrame,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
):
    """Compatibility wrapper around `indicators.volatility.keltner_channels`."""
    return _series_keltner_channels(
        df["high"],
        df["low"],
        df["close"],
        ema_period,
        atr_period,
        multiplier,
    )


def vwap(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.volume.vwap`."""
    return _series_vwap(df["high"], df["low"], df["close"], df["volume"])


def obv(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.volume.obv`."""
    return _series_obv(df["close"], df["volume"])


def candle_body(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.helpers.candle_body`."""
    return _candle_body(df["open"], df["close"])


def candle_range(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.helpers.candle_range`."""
    return _candle_range(df["high"], df["low"])


def is_green(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.helpers.is_green`."""
    return _is_green(df["open"], df["close"])


def is_red(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.helpers.is_red`."""
    return _is_red(df["open"], df["close"])


def upper_shadow(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.helpers.upper_shadow`."""
    return _upper_shadow(df["open"], df["high"], df["close"])


def lower_shadow(df: pd.DataFrame):
    """Compatibility wrapper around `indicators.helpers.lower_shadow`."""
    return _lower_shadow(df["open"], df["low"], df["close"])


__all__ = [
    "sma",
    "ema",
    "dema",
    "wma",
    "macd",
    "supertrend",
    "rsi",
    "stochastic",
    "roc",
    "cci",
    "atr",
    "adx",
    "bollinger_bands",
    "keltner_channels",
    "vwap",
    "obv",
    "zscore",
    "rolling_correlation",
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
