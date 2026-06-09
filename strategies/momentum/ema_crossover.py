# Use cases:
# - Trend-following equity or futures strategy based on fast/slow EMA crossover.
# - Reference implementation for vectorized strategies with explicit parameter schemas.
"""
strategies/momentum/ema_crossover.py
------------------------------------
EMA crossover strategy.
"""

from __future__ import annotations

import pandas as pd

from indicators.helpers import crossover, crossunder
from indicators.moving_averages import ema
from strategies.base import BaseStrategy


class EMACrossoverStrategy(BaseStrategy):
    """Buy on bullish EMA cross and exit/reverse on bearish cross."""

    PARAM_SCHEMA = [
        {"name": "fast_period", "type": "int", "default": 10, "min": 1, "max": 100, "step": 1},
        {"name": "slow_period", "type": "int", "default": 21, "min": 2, "max": 300, "step": 1},
    ]
    DESCRIPTION = "Momentum strategy using fast/slow EMA crossover."
    CATEGORY = "Momentum"

    def __init__(self, fast_period: int = 10, slow_period: int = 21) -> None:
        super().__init__(
            name="EMA Crossover",
            description=self.DESCRIPTION,
            params={"fast_period": int(fast_period), "slow_period": int(slow_period)},
        )

    def validate_params(self) -> None:
        super().validate_params()
        fast = int(self.params["fast_period"])
        slow = int(self.params["slow_period"])
        if fast < 1 or slow < 2:
            raise ValueError("EMA periods must be positive integers.")
        if fast >= slow:
            raise ValueError("fast_period must be less than slow_period.")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        fast = int(self.params["fast_period"])
        slow = int(self.params["slow_period"])

        df["ema_fast"] = self.I(ema, df["close"], fast, name=f"EMA_{fast}")
        df["ema_slow"] = self.I(ema, df["close"], slow, name=f"EMA_{slow}")
        df["cross_up"] = crossover(df["ema_fast"], df["ema_slow"])
        df["cross_down"] = crossunder(df["ema_fast"], df["ema_slow"])

        df.loc[df["cross_up"], "signal"] = 1
        df.loc[df["cross_down"], "signal"] = -1
        df.loc[df["cross_up"], "signal_tag"] = "EMA_CROSS_UP"
        df.loc[df["cross_down"], "signal_tag"] = "EMA_CROSS_DOWN"

        return self._suppress_warmup_signals(df, warmup_bars=slow)


__all__ = ["EMACrossoverStrategy"]
