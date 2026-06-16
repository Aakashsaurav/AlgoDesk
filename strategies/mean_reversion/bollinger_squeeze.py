"""
strategies/mean_reversion/bollinger_squeeze.py
----------------------------------------------
Bollinger squeeze breakout strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.categories import StrategyCategory
from strategies.base import BaseStrategy
from strategies.utils import long_short_state_signals, long_only_state_signals


class BollingerSqueezeStrategy(BaseStrategy):
    """Trade squeeze releases in the breakout direction."""
    PARAM_SCHEMA = [
        {"name": "bb_period", "type": "int", "default": 20, "min": 5, "max": 100, "step": 1, "label": "BB Period", "description": "Bollinger Bands lookback.", "unit": "bars", "optimize": True},
        {"name": "bb_std", "type": "float", "default": 2.0, "min": 1.0, "max": 5.0, "step": 0.1, "label": "BB Std Dev", "description": "Bollinger Bands standard deviation.", "optimize": True},
        {"name": "kc_ema", "type": "int", "default": 20, "min": 5, "max": 100, "step": 1, "label": "KC EMA", "description": "Keltner Channels EMA period.", "unit": "bars", "optimize": True},
        {"name": "kc_atr", "type": "int", "default": 20, "min": 5, "max": 100, "step": 1, "label": "KC ATR Period", "description": "ATR lookback for Keltner Channel.", "optimize": True},
        {"name": "kc_mult", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1, "label": "KC Multiplier", "description": "Keltner Channels multiplier.", "optimize": True},
        {"name": "position_mode", "type": "select", "default": "long_short", "options": ["long_short", "long_only", "short_only"], "label": "Position Mode", "description": "Allowed directions.", "optimize": False},
        {"name": "sl_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 20.0, "step": 0.5, "label": "Stop Loss %", "description": "Fixed stop loss percentage (0 to disable).", "optimize": True},
        {"name": "tp_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 50.0, "step": 0.5, "label": "Take Profit %", "description": "Fixed take profit percentage (0 to disable).", "optimize": True},
    ]
    DESCRIPTION = "Breakout strategy triggered by Bollinger/Keltner squeeze release."
    CATEGORY = StrategyCategory.MEAN_REVERSION.value

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        kc_ema: int = 20,
        kc_atr: int = 20,
        kc_mult: float = 1.5,
        position_mode: str = "long_short",
        sl_pct: float = 0.0,
        tp_pct: float = 0.0,
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
                "position_mode": str(position_mode),
                "sl_pct": float(sl_pct),
                "tp_pct": float(tp_pct),
            },
        )

    @property
    def warmup_period(self) -> int:
        return max(int(self.params["bb_period"]), int(self.params["kc_ema"]), int(self.params["kc_atr"]))

    def validate_params(self) -> None:
        super().validate_params()
        mode = self.params["position_mode"]
        if int(self.params["bb_period"]) < 2:
            raise ValueError("bb_period must be at least 2.")
        if float(self.params["bb_std"]) <= 0:
            raise ValueError("bb_std must be positive.")
        if int(self.params["kc_ema"]) < 1 or int(self.params["kc_atr"]) < 1:
            raise ValueError("Keltner periods must be positive.")
        if float(self.params["kc_mult"]) <= 0:
            raise ValueError("kc_mult must be positive.")
        if mode not in ("long_short", "long_only", "short_only"):
            raise ValueError("Invalid position_mode.")

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
        
        # Calculate squeeze duration for confidence
        squeeze_duration = df["squeeze_on"].astype(int).groupby((~df["squeeze_on"]).cumsum()).cumsum()
        
        df["squeeze_release"] = df["squeeze_on"].shift(1).fillna(False) & ~df["squeeze_on"]
        
        long_breakout = df["squeeze_release"] & (df["close"] > df["bb_upper"])
        short_breakout = df["squeeze_release"] & (df["close"] < df["bb_lower"])
        
        # Exit when returning to moving average
        exit_long = df["close"] < df["bb_middle"]
        exit_short = df["close"] > df["bb_middle"]

        mode = self.params["position_mode"]

        if mode == "long_short":
            sig = long_short_state_signals(long_entry=long_breakout, short_entry=short_breakout, exit_long=exit_long, exit_short=exit_short)
        elif mode == "long_only":
            sig = long_only_state_signals(entry=long_breakout, exit_=exit_long)
        elif mode == "short_only":
            sig = -long_only_state_signals(entry=short_breakout, exit_=exit_short)
        else:
            sig = pd.Series(0, index=df.index)

        df["signal"] = sig
        df["signal_tag"] = ""
        
        df.loc[sig == 1, "signal_tag"] = "SQUEEZE_UP_ENTRY" if mode != "short_only" else "SQUEEZE_SHORT_COVER"
        df.loc[sig == -1, "signal_tag"] = "SQUEEZE_DOWN_ENTRY" if mode != "long_only" else "SQUEEZE_LONG_EXIT"
        
        # Confidence based on squeeze duration before release
        prev_duration = squeeze_duration.shift(1).fillna(0)
        conf = np.clip(prev_duration / 10.0, 0.0, 1.0)
        
        conf_arr = np.zeros(len(df), dtype=float)
        sig_vals = sig.values
        
        if mode != "short_only":
            conf_arr[sig_vals == 1] = conf[sig_vals == 1]
        if mode != "long_only":
            conf_arr[sig_vals == -1] = conf[sig_vals == -1]
            
        df["confidence"] = conf_arr

        return self._finalize_signals(df)

__all__ = ["BollingerSqueezeStrategy"]
