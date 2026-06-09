# Use cases:
# - Momentum strategy based on MACD line crossing the signal line.
# - Reference implementation for multi-output indicator usage through `self.I`.
"""
strategies/momentum/macd_crossover.py
-------------------------------------
MACD crossover strategy.
"""

from __future__ import annotations

import pandas as pd

from indicators.helpers import crossover, crossunder
from strategies.base import BaseStrategy


class MACDCrossoverStrategy(BaseStrategy):
    """Buy on MACD bullish crossover and exit/reverse on bearish crossover."""

    PARAM_SCHEMA = [
        {"name": "fast_period", "type": "int", "default": 12, "min": 1, "max": 100, "step": 1},
        {"name": "slow_period", "type": "int", "default": 26, "min": 2, "max": 300, "step": 1},
        {"name": "signal_period", "type": "int", "default": 9, "min": 1, "max": 100, "step": 1},
    ]
    DESCRIPTION = "Momentum strategy using MACD and its signal line."
    CATEGORY = "Momentum"

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> None:
        super().__init__(
            name="MACD Crossover",
            description=self.DESCRIPTION,
            params={
                "fast_period": int(fast_period),
                "slow_period": int(slow_period),
                "signal_period": int(signal_period),
            },
        )

    def validate_params(self) -> None:
        super().validate_params()
        fast = int(self.params["fast_period"])
        slow = int(self.params["slow_period"])
        signal = int(self.params["signal_period"])
        if min(fast, slow, signal) < 1:
            raise ValueError("MACD periods must be positive integers.")
        if fast >= slow:
            raise ValueError("fast_period must be less than slow_period.")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        macd_df = self.I(
            "macd",
            df["close"],
            int(self.params["fast_period"]),
            int(self.params["slow_period"]),
            int(self.params["signal_period"]),
            name="MACD",
        )
        df["macd"] = macd_df["macd"]
        df["macd_signal"] = macd_df["signal"]
        df["macd_histogram"] = macd_df["histogram"]
        df["cross_up"] = crossover(df["macd"], df["macd_signal"])
        df["cross_down"] = crossunder(df["macd"], df["macd_signal"])

        df.loc[df["cross_up"], "signal"] = 1
        df.loc[df["cross_down"], "signal"] = -1
        df.loc[df["cross_up"], "signal_tag"] = "MACD_CROSS_UP"
        df.loc[df["cross_down"], "signal_tag"] = "MACD_CROSS_DOWN"

        warmup = int(self.params["slow_period"]) + int(self.params["signal_period"])
        return self._suppress_warmup_signals(df, warmup_bars=warmup)


__all__ = ["MACDCrossoverStrategy"]
