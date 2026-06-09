# Use cases:
# - Provide concrete screening criteria built with the existing indicator module.
# - Keep reusable rule implementations for SMA crossover and RSI momentum.
"""
screener/rules.py
-----------------
Indicator-driven rules for the screener module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from indicators.engine import IndicatorEngine

from screener.base import ScreenRule


@dataclass
class GoldenCrossRule(ScreenRule):
    """Pass when a fast SMA crosses above a slow SMA."""

    fast_period: int = 50
    slow_period: int = 200
    _engine: IndicatorEngine = IndicatorEngine()

    @property
    def name(self) -> str:
        return "GoldenCross"

    def evaluate(self, df: pd.DataFrame) -> Optional[Dict[str, object]]:
        if len(df) < self.slow_period:
            return None
        fast = self._engine.compute("sma", df["close"], self.fast_period)
        slow = self._engine.compute("sma", df["close"], self.slow_period)
        if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
            return {
                "fast": fast.iloc[-1],
                "slow": slow.iloc[-1],
                "timestamp": str(df.index[-1]),
            }
        return None


@dataclass
class RSIRule(ScreenRule):
    """Pass when RSI touches an oversold threshold."""

    period: int = 14
    threshold: float = 30.0
    _engine: IndicatorEngine = IndicatorEngine()

    @property
    def name(self) -> str:
        return "RSI"

    def evaluate(self, df: pd.DataFrame) -> Optional[Dict[str, object]]:
        if len(df) < self.period:
            return None
        rsi = self._engine.compute("rsi", df["close"], self.period)
        if rsi.iloc[-1] < self.threshold:
            return {"value": float(rsi.iloc[-1]), "timestamp": str(df.index[-1])}
        return None
