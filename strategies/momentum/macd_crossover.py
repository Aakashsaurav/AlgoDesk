"""
strategies/momentum/macd_crossover.py
-------------------------------------
MACD crossover strategy.
"""

from __future__ import annotations

import pandas as pd

from indicators.helpers import crossover, crossunder
from strategies.categories import StrategyCategory
from strategies.base import BaseStrategy
from strategies.utils import long_short_state_signals, long_only_state_signals


class MACDCrossoverStrategy(BaseStrategy):
    """Buy on MACD bullish crossover and exit/reverse on bearish crossover."""
    PARAM_SCHEMA = [
        {"name": "fast_period", "type": "int", "default": 12, "min": 2, "max": 50, "step": 1, "label": "Fast Period", "description": "MACD fast period.", "unit": "bars", "optimize": True},
        {"name": "slow_period", "type": "int", "default": 26, "min": 10, "max": 200, "step": 1, "label": "Slow Period", "description": "MACD slow period.", "unit": "bars", "optimize": True},
        {"name": "signal_period", "type": "int", "default": 9, "min": 2, "max": 50, "step": 1, "label": "Signal Period", "description": "MACD signal period.", "unit": "bars", "optimize": True},
        {"name": "position_mode", "type": "select", "default": "long_short", "options": ["long_short", "long_only", "short_only"], "label": "Position Mode", "description": "Allowed directions.", "optimize": False},
        {"name": "sl_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 20.0, "step": 0.5, "label": "Stop Loss %", "description": "Fixed stop loss percentage (0 to disable).", "optimize": True},
        {"name": "tp_pct", "type": "float", "default": 0.0, "min": 0.0, "max": 50.0, "step": 0.5, "label": "Take Profit %", "description": "Fixed take profit percentage (0 to disable).", "optimize": True},
    ]
    DESCRIPTION = "Momentum strategy using MACD and its signal line."
    CATEGORY = StrategyCategory.MOMENTUM.value

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        position_mode: str = "long_short",
        sl_pct: float = 0.0,
        tp_pct: float = 0.0,
    ) -> None:
        super().__init__(
            name="MACD Crossover",
            description=self.DESCRIPTION,
            params={
                "fast_period": int(fast_period),
                "slow_period": int(slow_period),
                "signal_period": int(signal_period),
                "position_mode": str(position_mode),
                "sl_pct": float(sl_pct),
                "tp_pct": float(tp_pct),
            },
        )

    @property
    def warmup_period(self) -> int:
        return int(self.params["slow_period"]) + int(self.params["signal_period"])

    def validate_params(self) -> None:
        super().validate_params()
        fast = int(self.params["fast_period"])
        slow = int(self.params["slow_period"])
        signal = int(self.params["signal_period"])
        mode = self.params["position_mode"]
        
        if min(fast, slow, signal) < 1:
            raise ValueError("MACD periods must be positive integers.")
        if fast >= slow:
            raise ValueError("fast_period must be less than slow_period.")
        if mode not in ("long_short", "long_only", "short_only"):
            raise ValueError("Invalid position_mode.")

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
        
        cross_up = crossover(df["macd"], df["macd_signal"])
        cross_down = crossunder(df["macd"], df["macd_signal"])
        
        df["cross_up"] = cross_up
        df["cross_down"] = cross_down

        mode = self.params["position_mode"]
        if mode == "long_short":
            sig = long_short_state_signals(long_entry=cross_up, short_entry=cross_down)
        elif mode == "long_only":
            sig = long_only_state_signals(entry=cross_up, exit_=cross_down)
        elif mode == "short_only":
            sig = -long_only_state_signals(entry=cross_down, exit_=cross_up)

        df["signal"] = sig
        df["signal_tag"] = ""
        df.loc[sig == 1, "signal_tag"] = "MACD_CROSS_UP_ENTRY" if mode != "short_only" else "MACD_CROSS_UP_COVER"
        df.loc[sig == -1, "signal_tag"] = "MACD_CROSS_DOWN_ENTRY" if mode != "long_only" else "MACD_CROSS_DOWN_EXIT"

        return self._finalize_signals(df)


__all__ = ["MACDCrossoverStrategy"]
