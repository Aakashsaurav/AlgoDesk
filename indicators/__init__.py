"""
indicators package
==================

Canonical modular indicator layer for AlgoDesk.

The package is intentionally lazy so ``import indicators`` does not eagerly
import the heavier modules until one of their attributes is requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    # Engine
    "IndicatorEngine": ("indicators.engine", "IndicatorEngine"),
    "IndicatorSpec": ("indicators.engine", "IndicatorSpec"),
    # Bridge
    "IndicatorBridge": ("indicators.bridge", "IndicatorBridge"),
    "LibraryStatus": ("indicators.bridge", "LibraryStatus"),
    # Canonical modular indicators
    "sma": ("indicators.moving_averages", "sma"),
    "ema": ("indicators.moving_averages", "ema"),
    "dema": ("indicators.moving_averages", "dema"),
    "wma": ("indicators.moving_averages", "wma"),
    "vwap": ("indicators.volume", "vwap"),
    "rsi": ("indicators.oscillators", "rsi"),
    "stochastic": ("indicators.oscillators", "stochastic"),
    "macd": ("indicators.oscillators", "macd"),
    "roc": ("indicators.oscillators", "roc"),
    "cci": ("indicators.oscillators", "cci"),
    "atr": ("indicators.volatility", "atr"),
    "bollinger_bands": ("indicators.volatility", "bollinger_bands"),
    "keltner_channels": ("indicators.volatility", "keltner_channels"),
    "bb_squeeze": ("indicators.volatility", "bb_squeeze"),
    "supertrend": ("indicators.trend", "supertrend"),
    "adx": ("indicators.trend", "adx"),
    "obv": ("indicators.volume", "obv"),
    "zscore": ("indicators.statistics", "zscore"),
    "rolling_correlation": ("indicators.statistics", "rolling_correlation"),
    "rolling_beta": ("indicators.statistics", "rolling_beta"),
    "spread": ("indicators.statistics", "spread"),
    "half_life": ("indicators.statistics", "half_life"),
    "cointegration_test": ("indicators.statistics", "cointegration_test"),
    "crossover": ("indicators.helpers", "crossover"),
    "crossunder": ("indicators.helpers", "crossunder"),
    "above_threshold": ("indicators.helpers", "above_threshold"),
    "below_threshold": ("indicators.helpers", "below_threshold"),
    "candle_body": ("indicators.helpers", "candle_body"),
    "candle_range": ("indicators.helpers", "candle_range"),
    "is_green": ("indicators.helpers", "is_green"),
    "is_red": ("indicators.helpers", "is_red"),
    "upper_shadow": ("indicators.helpers", "upper_shadow"),
    "lower_shadow": ("indicators.helpers", "lower_shadow"),
    "relative_strength": ("indicators.relative_strength", "relative_strength"),
    "relative_strength_rank": ("indicators.relative_strength", "relative_strength_rank"),
    # Future namespaces
    "IndicatorRegistry": ("indicators.registry", "IndicatorRegistry"),
    "ExpressionParser": ("indicators.expression", "ExpressionParser"),
    "CustomIndicatorSpec": ("indicators.custom", "CustomIndicatorSpec"),
    "CustomIndicatorLoader": ("indicators.custom", "CustomIndicatorLoader"),
    "scan_all_candlestick": ("indicators.patterns", "scan_all_candlestick"),
    "scan_all_chart": ("indicators.patterns", "scan_all_chart"),
    "trend_structure": ("indicators.patterns", "trend_structure"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'indicators' has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(_LAZY_EXPORTS.keys()))


__all__ = sorted(_LAZY_EXPORTS.keys())
