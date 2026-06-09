# Use cases:
# - Trend-following strategy using Supertrend direction changes.
# - Reference implementation for directional filters and optional shorting.
"""
strategies/trend/supertrend_strategy.py
---------------------------------------
Supertrend strategy.
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy


class SupertrendStrategy(BaseStrategy):
    """Trade direction flips from the Supertrend indicator."""

    PARAM_SCHEMA = [
        {"name": "st_period", "type": "int", "default": 10, "min": 1, "max": 200, "step": 1},
        {"name": "st_multiplier", "type": "float", "default": 3.0, "min": 0.1, "max": 10.0, "step": 0.1},
        {"name": "allow_short", "type": "bool", "default": False},
    ]
    DESCRIPTION = "Trend-following strategy driven by Supertrend flips."
    CATEGORY = "Trend"

    def __init__(
        self,
        st_period: int = 10,
        st_multiplier: float = 3.0,
        allow_short: bool = False,
    ) -> None:
        super().__init__(
            name="Supertrend",
            description=self.DESCRIPTION,
            params={
                "st_period": int(st_period),
                "st_multiplier": float(st_multiplier),
                "allow_short": bool(allow_short),
            },
        )

    def validate_params(self) -> None:
        super().validate_params()
        if int(self.params["st_period"]) < 1:
            raise ValueError("st_period must be positive.")
        if float(self.params["st_multiplier"]) <= 0:
            raise ValueError("st_multiplier must be positive.")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        st = self.I(
            "supertrend",
            df["high"],
            df["low"],
            df["close"],
            int(self.params["st_period"]),
            float(self.params["st_multiplier"]),
            name="Supertrend",
        )
        df["supertrend"] = st["supertrend"]
        df["st_direction"] = st["direction"]
        df["st_buy"] = st["buy_signal"]
        df["st_sell"] = st["sell_signal"]

        df.loc[df["st_buy"], "signal"] = 1
        if bool(self.params["allow_short"]):
            df.loc[df["st_sell"], "signal"] = -1
            df.loc[df["st_sell"], "signal_tag"] = "ST_SHORT"
        else:
            df.loc[df["st_sell"], "signal"] = -1
            df.loc[df["st_sell"], "signal_tag"] = "ST_EXIT"
        df.loc[df["st_buy"], "signal_tag"] = "ST_BUY"

        return self._suppress_warmup_signals(df, warmup_bars=int(self.params["st_period"]))

    def on_entry_stop(self, bar_idx: int, row: pd.Series, direction: int):
        value = row.get("supertrend")
        if pd.notna(value):
            return float(value)
        return None


__all__ = ["SupertrendStrategy"]
