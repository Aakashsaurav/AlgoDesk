"""
indicators/volume.py
--------------------
Volume-based indicators.

Note on Caching: These functions do not use @functools.lru_cache directly.
Memoization/caching is handled exclusively by the IndicatorEngine to
prevent memory leaks on large live-streaming datasets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from indicators.registry import register_indicator


@register_indicator(
    name="vwap",
    category="VOLUME",
    inputs=["high", "low", "close", "volume"],
    outputs=["vwap"],
    parameters={},
    display_name="Volume Weighted Average Price",
    output_type="series",
    libraries=["built_in", "pandas_ta"],
    description="Volume Weighted Average Price",
    example="vwap(high, low, close, volume)"
)
def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Volume Weighted Average Price.

    For intraday data with a DatetimeIndex, VWAP resets each trading day.
    For non-datetime indices, it is computed across the full series.

    NOTE ON TIMEZONES: Ensure the DatetimeIndex is timezone-aware (e.g. IST)
    before calling vwap, so that `index.date` correctly identifies market days.
    """
    if close.empty:
        return pd.Series(dtype=float, index=close.index, name="VWAP")

    typical_price = (high + low + close) / 3
    price_volume = typical_price * volume

    if isinstance(close.index, pd.DatetimeIndex):
        session_key = pd.Series(close.index.date, index=close.index)
        cumulative_pv = price_volume.groupby(session_key).cumsum()
        cumulative_volume = volume.groupby(session_key).cumsum()
    else:
        cumulative_pv = price_volume.cumsum()
        cumulative_volume = volume.cumsum()

    result = cumulative_pv / cumulative_volume.replace(0, np.nan)
    result.name = "VWAP"
    return result


@register_indicator(
    name="obv",
    category="VOLUME",
    inputs=["close", "volume"],
    outputs=["obv"],
    parameters={},
    display_name="On Balance Volume",
    output_type="series",
    libraries=["built_in", "talib", "pandas_ta"],
    description="On Balance Volume",
    example="obv(close, volume)"
)
def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On Balance Volume."""
    if close.empty:
        return pd.Series(dtype=float, index=close.index, name="OBV")

    direction = np.sign(close.diff().fillna(0.0))
    result = (direction * volume).cumsum()
    result.name = "OBV"
    return result


__all__ = ["vwap", "obv"]
