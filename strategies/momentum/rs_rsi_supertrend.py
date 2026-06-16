"""
strategies/momentum/rs_rsi_supertrend.py
--------------------------------
RS + RSI + Supertrend Combo Strategy
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.categories import StrategyCategory
from strategies.base import BaseStrategy
from strategies.utils import long_only_state_signals
from indicators.relative_strength import relative_strength


class RSRSISupertrend(BaseStrategy):
    """
    Relative Strength + RSI + Supertrend momentum strategy.
    """
    PARAM_SCHEMA = [
        {"name": "rs_period", "type": "int", "default": 55, "min": 10, "max": 200, "step": 1, "label": "RS Period", "description": "Relative Strength period.", "unit": "bars", "optimize": True},
        {"name": "rsi_period", "type": "int", "default": 14, "min": 2, "max": 100, "step": 1, "label": "RSI Period", "description": "RSI period.", "unit": "bars", "optimize": True},
        {"name": "rsi_buy_level", "type": "int", "default": 55, "min": 30, "max": 80, "step": 1, "label": "RSI Buy Level", "description": "RSI value above which to buy.", "optimize": True},
        {"name": "st_period", "type": "int", "default": 10, "min": 3, "max": 50, "step": 1, "label": "ST Period", "description": "Supertrend ATR period.", "unit": "bars", "optimize": True},
        {"name": "st_multiplier", "type": "float", "default": 3.0, "min": 1.0, "max": 10.0, "step": 0.1, "label": "ST Multiplier", "description": "Supertrend multiplier.", "optimize": True},
        {"name": "sl_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 20.0, "step": 0.5, "label": "Stop Loss %", "description": "Fixed stop loss percentage (0 to disable).", "optimize": True},
        {"name": "tp_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 50.0, "step": 0.5, "label": "Take Profit %", "description": "Fixed take profit percentage (0 to disable).", "optimize": True},
    ]
    DESCRIPTION = (
        "Buy when RS(55)>0 AND RSI(14)>threshold AND Supertrend(10,3) is bullish. "
        "Sell when any two of those conditions fail."
    )
    CATEGORY = StrategyCategory.MOMENTUM.value
    REQUIRED_EXTRA_COLUMNS = ("benchmark_close",)

    def __init__(
        self,
        rs_period:      int   = 55,
        rsi_period:     int   = 14,
        rsi_buy_level:  float = 55.0,
        st_period:      int   = 10,
        st_multiplier:  float = 3.0,
        sl_pct:         float = 0.0,
        tp_pct:         float = 0.0,
    ) -> None:
        super().__init__(
            name="RS-RSI-Supertrend",
            description=self.DESCRIPTION,
            params={
                "rs_period":     int(rs_period),
                "rsi_period":    int(rsi_period),
                "rsi_buy_level": float(rsi_buy_level),
                "st_period":     int(st_period),
                "st_multiplier": float(st_multiplier),
                "sl_pct":        float(sl_pct),
                "tp_pct":        float(tp_pct),
            },
        )

    @property
    def warmup_period(self) -> int:
        rs_p    = int(self.params["rs_period"])
        rsi_p   = int(self.params["rsi_period"])
        st_p    = int(self.params["st_period"])
        return max(rs_p, rsi_p, st_p) + 5

    def validate_params(self) -> None:
        super().validate_params()
        if int(self.params["rs_period"]) < 1:
            raise ValueError("rs_period must be >= 1")
        if int(self.params["rsi_period"]) < 2:
            raise ValueError("rsi_period must be >= 2")
        if not (0 < float(self.params["rsi_buy_level"]) < 100):
            raise ValueError("rsi_buy_level must be between 0 and 100")
        if int(self.params["st_period"]) < 1:
            raise ValueError("st_period must be >= 1")
        if float(self.params["st_multiplier"]) <= 0:
            raise ValueError("st_multiplier must be > 0")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        if "benchmark_close" not in df.columns:
            raise ValueError("Missing required column: 'benchmark_close'")
            
        benchmark_close = df["benchmark_close"]
        if benchmark_close.isna().all():
            raise ValueError("The 'benchmark_close' column contains all NaNs.")

        # Validate overlap percentage
        valid_overlap = df["close"].notna() & benchmark_close.notna()
        if len(df) > 0 and valid_overlap.sum() / len(df) < 0.5:
            self.logger.warning("Less than 50% overlap between stock and benchmark.")

        rs_p    = int(self.params["rs_period"])
        rsi_p   = int(self.params["rsi_period"])
        rsi_thr = float(self.params["rsi_buy_level"])
        st_p    = int(self.params["st_period"])
        st_m    = float(self.params["st_multiplier"])

        try:
            rs_series = relative_strength(df["close"], benchmark_close, period=rs_p)
            rs_aligned = rs_series.reindex(df.index)
        except Exception as e:
            self.logger.warning("RS computation failed: %s. Filling with NaN.", e)
            rs_aligned = pd.Series(np.nan, index=df.index, name=f"RS_{rs_p}")

        df["rs"] = rs_aligned
        df["rsi"] = self.I("rsi", df["close"], rsi_p, name=f"RSI_{rsi_p}")

        st = self.I(
            "supertrend",
            df["high"], df["low"], df["close"],
            st_p, st_m,
            name=f"ST_{st_p}_{st_m}",
        )
        df["supertrend"]   = st["supertrend"]
        df["st_direction"] = st["direction"]

        df["cond_rs"]  = df["rs"]  > 0
        df["cond_rsi"] = df["rsi"] > rsi_thr
        df["cond_st"]  = df["st_direction"] == 1

        df["n_true"] = (
            df["cond_rs"].astype(int) +
            df["cond_rsi"].astype(int) +
            df["cond_st"].astype(int)
        )

        long_entry = df["n_true"] == 3
        exit_long = df["n_true"] < 2

        sig = long_only_state_signals(entry=long_entry, exit_=exit_long)
        df["signal"] = sig

        df["signal_tag"] = ""
        df.loc[sig == 1, "signal_tag"] = "RS_RSI_ST_ENTRY"
        df.loc[sig == -1, "signal_tag"] = "RS_RSI_ST_EXIT"

        df["confidence"] = df["n_true"] / 3.0

        return self._finalize_signals(df)

__all__ = ["RSRSISupertrend"]