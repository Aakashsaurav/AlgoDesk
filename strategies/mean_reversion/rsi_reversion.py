"""
strategies/mean_reversion/rsi_reversion.py
------------------------------------------
RSI mean reversion strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.categories import StrategyCategory
from strategies.base import BaseStrategy
from strategies.utils import long_short_state_signals, long_only_state_signals


class RSIReversionStrategy(BaseStrategy):
    """Mean reversion strategy based on RSI extremes."""
    PARAM_SCHEMA = [
        {"name": "rsi_period", "type": "int", "default": 14, "min": 2, "max": 100, "step": 1, "label": "RSI Period", "description": "Lookback period for RSI.", "unit": "bars", "optimize": True},
        {"name": "oversold", "type": "int", "default": 30, "min": 1, "max": 50, "step": 1, "label": "Oversold Level", "description": "RSI level to enter long.", "optimize": True},
        {"name": "overbought", "type": "int", "default": 70, "min": 50, "max": 99, "step": 1, "label": "Overbought Level", "description": "RSI level to enter short / exit long.", "optimize": True},
        {"name": "exit_midline", "type": "int", "default": 50, "min": 1, "max": 99, "step": 1, "label": "Exit Midline", "description": "RSI midline to exit positions.", "optimize": True},
        {"name": "position_mode", "type": "select", "default": "long_short", "options": ["long_short", "long_only", "short_only"], "label": "Position Mode", "description": "Allowed directions.", "optimize": False},
        {"name": "sl_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 20.0, "step": 0.5, "label": "Stop Loss %", "description": "Fixed stop loss percentage (0 to disable).", "optimize": True},
        {"name": "tp_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 50.0, "step": 0.5, "label": "Take Profit %", "description": "Fixed take profit percentage (0 to disable).", "optimize": True},
    ]
    DESCRIPTION = "Mean reversion strategy driven by RSI extremes."
    CATEGORY = StrategyCategory.MEAN_REVERSION.value

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: int = 30,
        overbought: int = 70,
        exit_midline: int = 50,
        position_mode: str = "long_short",
        sl_pct: float = 0.0,
        tp_pct: float = 0.0,
    ) -> None:
        super().__init__(
            name="RSI Mean Reversion",
            description=self.DESCRIPTION,
            params={
                "rsi_period": int(rsi_period),
                "oversold": int(oversold),
                "overbought": int(overbought),
                "exit_midline": int(exit_midline),
                "position_mode": str(position_mode),
                "sl_pct": float(sl_pct),
                "tp_pct": float(tp_pct),
            },
        )

    @property
    def warmup_period(self) -> int:
        return int(self.params["rsi_period"])

    def validate_params(self) -> None:
        super().validate_params()
        oversold = int(self.params["oversold"])
        overbought = int(self.params["overbought"])
        exit_midline = int(self.params["exit_midline"])
        mode = self.params["position_mode"]
        if int(self.params["rsi_period"]) < 2:
            raise ValueError("rsi_period must be at least 2.")
        if not (0 < oversold < exit_midline < overbought < 100):
            raise ValueError(
                "RSI thresholds must satisfy 0 < oversold < exit_midline < overbought < 100."
            )
        if mode not in ("long_short", "long_only", "short_only"):
            raise ValueError("Invalid position_mode.")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)

        period = int(self.params["rsi_period"])
        oversold = int(self.params["oversold"])
        overbought = int(self.params["overbought"])
        exit_midline = int(self.params["exit_midline"])
        mode = self.params["position_mode"]

        df["rsi"] = self.I("rsi", df["close"], period, name=f"RSI_{period}")
        
        long_entry = df["rsi"] < oversold
        exit_long = (df["rsi"] > overbought) | ((df["rsi"] > exit_midline) & (df["rsi"].shift(1) <= exit_midline))
        
        short_entry = df["rsi"] > overbought
        exit_short = (df["rsi"] < oversold) | ((df["rsi"] < exit_midline) & (df["rsi"].shift(1) >= exit_midline))

        if mode == "long_short":
            sig = long_short_state_signals(long_entry=long_entry, short_entry=short_entry, exit_long=exit_long, exit_short=exit_short)
        elif mode == "long_only":
            sig = long_only_state_signals(entry=long_entry, exit_=exit_long)
        elif mode == "short_only":
            sig = -long_only_state_signals(entry=short_entry, exit_=exit_short)
        else:
            sig = pd.Series(0, index=df.index)

        df["signal"] = sig
        df["signal_tag"] = ""
        
        # Tag signals based on direction and mode
        df.loc[sig == 1, "signal_tag"] = "RSI_OVERSOLD_ENTRY" if mode != "short_only" else "RSI_EXIT_SHORT"
        df.loc[sig == -1, "signal_tag"] = "RSI_OVERBOUGHT_ENTRY" if mode != "long_only" else "RSI_EXIT_LONG"
        
        # Calculate confidence metric
        rsi_vals = df["rsi"].values
        long_conf = np.clip((oversold - rsi_vals) / oversold, 0.0, 1.0)
        short_conf = np.clip((rsi_vals - overbought) / (100.0 - overbought), 0.0, 1.0)
        
        # Assign confidence relative to the active signal
        sig_vals = sig.values
        conf_arr = np.zeros(len(df), dtype=float)
        
        if mode != "short_only":
            conf_arr[sig_vals == 1] = long_conf[sig_vals == 1]
            
        if mode != "long_only":
            conf_arr[sig_vals == -1] = short_conf[sig_vals == -1]
            
        df["confidence"] = conf_arr

        return self._finalize_signals(df)


__all__ = ["RSIReversionStrategy"]
