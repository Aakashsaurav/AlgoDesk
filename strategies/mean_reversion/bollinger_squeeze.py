# Use cases:
# - Volatility compression breakout strategy using Bollinger Bands and Keltner Channels.
# - Reference implementation for combining multiple built-in indicators.
"""
strategies/mean_reversion/bollinger_squeeze.py
----------------------------------------------
Bollinger squeeze breakout strategy.
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy


class BollingerSqueezeStrategy(BaseStrategy):
    """Trade squeeze releases in the breakout direction."""

    PARAM_SCHEMA = [
        {"name": "bb_period", "type": "int", "default": 20, "min": 2, "max": 200, "step": 1},
        {"name": "bb_std", "type": "float", "default": 2.0, "min": 0.1, "max": 5.0, "step": 0.1},
        {"name": "kc_ema", "type": "int", "default": 20, "min": 1, "max": 200, "step": 1},
        {"name": "kc_atr", "type": "int", "default": 10, "min": 1, "max": 200, "step": 1},
        {"name": "kc_mult", "type": "float", "default": 1.5, "min": 0.1, "max": 5.0, "step": 0.1},
    ]
    DESCRIPTION = "Breakout strategy triggered by Bollinger/Keltner squeeze release."
    CATEGORY = "Mean Reversion"

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        kc_ema: int = 20,
        kc_atr: int = 10,
        kc_mult: float = 1.5,
    ) -> None:
        super().__init__(
            name="Bollinger Squeeze",
            description=self.DESCRIPTION,
            params={
                "bb_period": int(bb_period),
                "bb_std": float(bb_std),
                "kc_ema": int(kc_ema),
                "kc_atr": int(kc_atr),
                "kc_mult": float(kc_mult),
            },
        )

    def validate_params(self) -> None:
        super().validate_params()
        if int(self.params["bb_period"]) < 2:
            raise ValueError("bb_period must be at least 2.")
        if float(self.params["bb_std"]) <= 0:
            raise ValueError("bb_std must be positive.")
        if int(self.params["kc_ema"]) < 1 or int(self.params["kc_atr"]) < 1:
            raise ValueError("Keltner periods must be positive.")
        if float(self.params["kc_mult"]) <= 0:
            raise ValueError("kc_mult must be positive.")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        bb = self.I(
            "bollinger_bands",
            df["close"],
            int(self.params["bb_period"]),
            float(self.params["bb_std"]),
            name="BB",
        )
        kc = self.I(
            "keltner_channels",
            df["high"],
            df["low"],
            df["close"],
            int(self.params["kc_ema"]),
            int(self.params["kc_atr"]),
            float(self.params["kc_mult"]),
            name="KC",
        )

        df["bb_upper"] = bb["bb_upper"]
        df["bb_middle"] = bb["bb_middle"]
        df["bb_lower"] = bb["bb_lower"]
        df["kc_upper"] = kc["kc_upper"]
        df["kc_middle"] = kc["kc_middle"]
        df["kc_lower"] = kc["kc_lower"]

        df["squeeze_on"] = (df["bb_upper"] < df["kc_upper"]) & (df["bb_lower"] > df["kc_lower"])
        df["squeeze_release"] = df["squeeze_on"].shift(1).fillna(False) & ~df["squeeze_on"]
        df["long_breakout"] = df["squeeze_release"] & (df["close"] > df["bb_upper"])
        df["short_breakout"] = df["squeeze_release"] & (df["close"] < df["bb_lower"])

        df.loc[df["long_breakout"], "signal"] = 1
        df.loc[df["short_breakout"], "signal"] = -1
        df.loc[df["long_breakout"], "signal_tag"] = "SQUEEZE_UP"
        df.loc[df["short_breakout"], "signal_tag"] = "SQUEEZE_DOWN"

        warmup = max(int(self.params["bb_period"]), int(self.params["kc_ema"]), int(self.params["kc_atr"]))
        return self._suppress_warmup_signals(df, warmup_bars=warmup)


__all__ = ["BollingerSqueezeStrategy"]
