"""
strategies/momentum/rs_rsi_supertrend.py
--------------------------------
RS + RSI + Supertrend Combo Strategy

ENTRY (BUY signal = 1):
    All three conditions must be true:
      1. RS(55)  > 0         → stock outperforming NIFTY over last 55 bars
      2. RSI(14) > rsi_threshold (default 50)
      3. Supertrend(10, 3)   > 0  (direction = +1, price above supertrend line)

EXIT (SELL signal = -1):
    Any TWO of the above three conditions fail (i.e., fewer than 2 remain true).

This "2-of-3 failure" exit rule keeps you in a trade as long as the
majority of signals remain favourable — more robust than a hard stop
on any single indicator.

DESIGN:
    - Subclasses BaseStrategy following the existing AlgoDesk pattern.
    - Accepts benchmark_close via constructor for RS computation.
    - Uses self.I() for RSI and Supertrend (consistent with other strategies).
    - RS is computed directly (not via self.I) since it needs two series.
    - Warm-up period = max(RS period, RSI period, Supertrend ATR period).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ── Internal project imports ──────────────────────────────────────────────────
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import BaseStrategy
from indicators.relative_strength import relative_strength


class RSRSISupertrend(BaseStrategy):
    """
    Relative Strength + RSI + Supertrend momentum strategy.

    Parameters
    ----------
    benchmark_close : pd.Series
        NIFTY (or any benchmark) daily closing prices. Must overlap with
        the stock data passed to generate_signals().
    rs_period : int
        Lookback for Relative Strength calculation. Default 55.
    rsi_period : int
        RSI lookback. Default 14.
    rsi_threshold : float
        Minimum RSI required for a bullish signal. Default 50.
    st_period : int
        ATR period for Supertrend. Default 10.
    st_multiplier : float
        ATR multiplier for Supertrend bands. Default 3.0.
    """

    PARAM_SCHEMA = [
        {"name": "rs_period",      "type": "int",   "default": 55,  "min": 10,  "max": 200, "step": 5},
        {"name": "rsi_period",     "type": "int",   "default": 14,  "min": 5,   "max": 50,  "step": 1},
        {"name": "rsi_threshold",  "type": "float", "default": 50.0,"min": 30.0,"max": 70.0,"step": 1.0},
        {"name": "st_period",      "type": "int",   "default": 10,  "min": 5,   "max": 50,  "step": 1},
        {"name": "st_multiplier",  "type": "float", "default": 3.0, "min": 1.0, "max": 6.0, "step": 0.5},
    ]
    DESCRIPTION = (
        "Buy when RS(55)>0 AND RSI(14)>threshold AND Supertrend(10,3) is bullish. "
        "Sell when any two of those conditions fail."
    )
    CATEGORY = "Momentum"

    def __init__(
        self,
        benchmark_close: pd.Series,
        rs_period:      int   = 55,
        rsi_period:     int   = 14,
        rsi_threshold:  float = 50.0,
        st_period:      int   = 10,
        st_multiplier:  float = 3.0,
    ) -> None:
        super().__init__(
            name="RS-RSI-Supertrend",
            description=self.DESCRIPTION,
            params={
                "rs_period":     int(rs_period),
                "rsi_period":    int(rsi_period),
                "rsi_threshold": float(rsi_threshold),
                "st_period":     int(st_period),
                "st_multiplier": float(st_multiplier),
            },
        )
        self.benchmark_close = benchmark_close

    # ── Param validation ──────────────────────────────────────────────────────

    def validate_params(self) -> None:
        super().validate_params()
        if int(self.params["rs_period"]) < 1:
            raise ValueError("rs_period must be >= 1")
        if int(self.params["rsi_period"]) < 2:
            raise ValueError("rsi_period must be >= 2")
        if not (0 < float(self.params["rsi_threshold"]) < 100):
            raise ValueError("rsi_threshold must be between 0 and 100")
        if int(self.params["st_period"]) < 1:
            raise ValueError("st_period must be >= 1")
        if float(self.params["st_multiplier"]) <= 0:
            raise ValueError("st_multiplier must be > 0")

    # ── Main signal generation ────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute RS, RSI, Supertrend and apply the entry/exit logic.

        Entry: all three bullish conditions hold simultaneously.
        Exit:  fewer than two conditions remain bullish (any two fail).

        Adds columns to df:
            rs            : Relative Strength vs benchmark
            rsi           : RSI values
            supertrend    : Supertrend line values
            st_direction  : +1 (bullish) / -1 (bearish)
            cond_rs       : bool — RS condition
            cond_rsi      : bool — RSI condition
            cond_st       : bool — Supertrend condition
            signal        : +1 buy / -1 sell / 0 hold
        """
        df = self._validate_and_prepare(df)

        rs_p    = int(self.params["rs_period"])
        rsi_p   = int(self.params["rsi_period"])
        rsi_thr = float(self.params["rsi_threshold"])
        st_p    = int(self.params["st_period"])
        st_m    = float(self.params["st_multiplier"])

        # ── 1. Relative Strength ──────────────────────────────────────────────
        try:
            rs_series = relative_strength(df["close"], self.benchmark_close, period=rs_p)
            # Align to df's index (inner join may have dropped rows)
            rs_aligned = rs_series.reindex(df.index)
        except Exception as e:
            self.logger.warning(f"RS computation failed: {e}. Filling with NaN.")
            rs_aligned = pd.Series(np.nan, index=df.index, name=f"RS_{rs_p}")

        df["rs"] = rs_aligned

        # ── 2. RSI ────────────────────────────────────────────────────────────
        df["rsi"] = self.I("rsi", df["close"], rsi_p, name=f"RSI_{rsi_p}")

        # ── 3. Supertrend ─────────────────────────────────────────────────────
        st = self.I(
            "supertrend",
            df["high"], df["low"], df["close"],
            st_p, st_m,
            name=f"ST_{st_p}_{st_m}",
        )
        df["supertrend"]   = st["supertrend"]
        df["st_direction"] = st["direction"]

        # ── 4. Individual boolean conditions ─────────────────────────────────
        df["cond_rs"]  = df["rs"]  > 0
        df["cond_rsi"] = df["rsi"] > rsi_thr
        df["cond_st"]  = df["st_direction"] == 1

        # ── 5. Entry / exit logic ─────────────────────────────────────────────
        # Count how many conditions are True at each bar
        df["n_true"] = (
            df["cond_rs"].astype(int) +
            df["cond_rsi"].astype(int) +
            df["cond_st"].astype(int)
        )

        # Entry: all 3 conditions true
        all_bullish = df["n_true"] == 3

        # Exit: any 2 conditions fail = fewer than 2 true
        two_or_more_fail = df["n_true"] < 2

        # Assign raw signals (before warm-up suppression)
        df.loc[all_bullish,       "signal"] = 1
        df.loc[two_or_more_fail,  "signal"] = -1

        # ── 6. State-aware signal generation (avoid re-entry while already long)
        # Walk through to produce clean entry/exit pairs
        df = self._make_state_signals(df)

        # ── 7. Suppress warm-up period ─────────────────────────────────────────
        warmup = max(rs_p, rsi_p, st_p) + 5
        df = self._suppress_warmup_signals(df, warmup_bars=warmup)

        return df

    # ── State-machine to avoid duplicate entries ──────────────────────────────

    def _make_state_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert the raw vectorised signals into clean entry/exit pairs.

        Rules:
          - If not in a position and all_bullish → enter (signal = 1)
          - If in a position and two_or_more_fail → exit (signal = -1)
          - All other bars get signal = 0
        """
        signals   = df["signal"].values.copy()
        n_true    = df["n_true"].values
        clean_sig = np.zeros(len(df), dtype=int)
        in_trade  = False

        for i in range(len(df)):
            if not in_trade:
                if n_true[i] == 3:
                    clean_sig[i] = 1
                    in_trade = True
            else:
                if n_true[i] < 2:
                    clean_sig[i] = -1
                    in_trade = False

        df["signal"] = clean_sig
        return df