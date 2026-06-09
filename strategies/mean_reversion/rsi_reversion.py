# Use cases:
# - Mean-reversion strategy that buys oversold conditions and exits on normalization.
# - Reference implementation for single-series oscillators in the strategy layer.
"""
strategies/mean_reversion/rsi_reversion.py
------------------------------------------
RSI mean reversion strategy.
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy


class RSIReversionStrategy(BaseStrategy):
    """Buy oversold RSI and exit on recovery or overbought condition."""

    PARAM_SCHEMA = [
        {"name": "rsi_period", "type": "int", "default": 14, "min": 2, "max": 100, "step": 1},
        {"name": "oversold", "type": "int", "default": 30, "min": 1, "max": 50, "step": 1},
        {"name": "overbought", "type": "int", "default": 70, "min": 50, "max": 99, "step": 1},
        {"name": "exit_midline", "type": "int", "default": 50, "min": 1, "max": 99, "step": 1},
    ]
    DESCRIPTION = "Mean reversion strategy driven by RSI extremes."
    CATEGORY = "Mean Reversion"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: int = 30,
        overbought: int = 70,
        exit_midline: int = 50,
    ) -> None:
        super().__init__(
            name="RSI Mean Reversion",
            description=self.DESCRIPTION,
            params={
                "rsi_period": int(rsi_period),
                "oversold": int(oversold),
                "overbought": int(overbought),
                "exit_midline": int(exit_midline),
            },
        )

    def validate_params(self) -> None:
        super().validate_params()
        oversold = int(self.params["oversold"])
        overbought = int(self.params["overbought"])
        exit_midline = int(self.params["exit_midline"])
        if int(self.params["rsi_period"]) < 2:
            raise ValueError("rsi_period must be at least 2.")
        if not (0 < oversold < exit_midline < overbought < 100):
            raise ValueError(
                "RSI thresholds must satisfy 0 < oversold < exit_midline < overbought < 100."
            )

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        period = int(self.params["rsi_period"])
        oversold = int(self.params["oversold"])
        overbought = int(self.params["overbought"])
        exit_midline = int(self.params["exit_midline"])

        df["rsi"] = self.I("rsi", df["close"], period, name=f"RSI_{period}")
        df["long_entry"] = df["rsi"] < oversold
        df["exit_signal"] = (df["rsi"] > overbought) | (
            (df["rsi"] > exit_midline) & (df["rsi"].shift(1) <= exit_midline)
        )

        df.loc[df["long_entry"], "signal"] = 1
        df.loc[df["exit_signal"], "signal"] = -1
        df.loc[df["long_entry"], "signal_tag"] = "RSI_OVERSOLD"
        df.loc[df["exit_signal"], "signal_tag"] = "RSI_EXIT"

        return self._suppress_warmup_signals(df, warmup_bars=period)


__all__ = ["RSIReversionStrategy"]
