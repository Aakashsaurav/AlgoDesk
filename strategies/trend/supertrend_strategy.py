"""
strategies/trend/supertrend_strategy.py
---------------------------------------
Supertrend strategy.
"""

from __future__ import annotations

import pandas as pd

from strategies.categories import StrategyCategory
from strategies.base import BaseStrategy
from strategies.utils import long_short_state_signals, long_only_state_signals


class SupertrendStrategy(BaseStrategy):
    """Trade direction flips from the Supertrend indicator."""
    PARAM_SCHEMA = [
        {"name": "st_period", "type": "int", "default": 10, "min": 3, "max": 50, "step": 1, "label": "ST Period", "description": "Supertrend ATR period.", "unit": "bars", "optimize": True},
        {"name": "st_multiplier", "type": "float", "default": 3.0, "min": 1.0, "max": 10.0, "step": 0.1, "label": "ST Multiplier", "description": "Supertrend multiplier.", "optimize": True},
        {"name": "position_mode", "type": "select", "default": "long_short", "options": ["long_short", "long_only", "short_only"], "label": "Position Mode", "description": "Allowed directions.", "optimize": False},
        {"name": "allow_short", "type": "bool", "default": True, "label": "Allow Shorting (Legacy)", "description": "Legacy alias for position_mode.", "optimize": False, "runtime_only": True},
    ]
    DESCRIPTION = "Trend-following strategy driven by Supertrend flips."
    CATEGORY = StrategyCategory.TREND.value

    def __init__(
        self,
        st_period: int = 10,
        st_multiplier: float = 3.0,
        position_mode: str = "long_short",
        allow_short: bool = True,
    ) -> None:
        
        # Convert legacy allow_short to position_mode if explicitly passed as False
        if not allow_short and position_mode == "long_short":
            position_mode = "long_only"
            
        super().__init__(
            name="Supertrend",
            description=self.DESCRIPTION,
            params={
                "st_period": int(st_period),
                "st_multiplier": float(st_multiplier),
                "position_mode": str(position_mode),
                "allow_short": bool(allow_short),
            },
        )

    @property
    def warmup_period(self) -> int:
        return int(self.params["st_period"])

    def validate_params(self) -> None:
        super().validate_params()
        if int(self.params["st_period"]) < 1:
            raise ValueError("st_period must be positive.")
        if float(self.params["st_multiplier"]) <= 0:
            raise ValueError("st_multiplier must be positive.")
        mode = self.params["position_mode"]
        if mode not in ("long_short", "long_only", "short_only"):
            raise ValueError("Invalid position_mode.")

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
        
        st_buy = st["buy_signal"]
        st_sell = st["sell_signal"]

        mode = self.params["position_mode"]

        if mode == "long_short":
            sig = long_short_state_signals(long_entry=st_buy, short_entry=st_sell)
        elif mode == "long_only":
            sig = long_only_state_signals(entry=st_buy, exit_=st_sell)
        elif mode == "short_only":
            sig = -long_only_state_signals(entry=st_sell, exit_=st_buy)
        else:
            sig = pd.Series(0, index=df.index)

        df["signal"] = sig
        df["signal_tag"] = ""
        
        df.loc[sig == 1, "signal_tag"] = "ST_BUY_ENTRY" if mode != "short_only" else "ST_SHORT_COVER"
        df.loc[sig == -1, "signal_tag"] = "ST_SELL_ENTRY" if mode != "long_only" else "ST_LONG_EXIT"
        
        df["stop_loss"] = df["supertrend"]

        from strategies.utils import build_order_spec
        sig_vals = sig.values
        st_vals = df["supertrend"].values
        order_specs = [None] * len(df)
        for i, (sv, st_val) in enumerate(zip(sig_vals, st_vals)):
            if sv in (1, -1) and pd.notna(st_val):
                order_specs[i] = build_order_spec(
                    direction=int(sv),
                    order_type_str="MARKET",
                    sl_type_str="FIXED_PRICE",
                    sl_value=float(st_val),
                )
        df["order_spec"] = order_specs

        return self._finalize_signals(df)

    def on_entry_stop(self, bar_idx: int, row: pd.Series, direction: int):
        # Kept for backtester compatibility
        value = row.get("supertrend")
        if pd.notna(value):
            return float(value)
        return None


__all__ = ["SupertrendStrategy"]
