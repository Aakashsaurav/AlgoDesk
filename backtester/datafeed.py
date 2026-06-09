"""
backtester/datafeed.py
-----------------------
Standalone market-data feed abstraction for the backtester.

Use cases:
  - Validate OHLCV input before sending it to the backtest engine.
  - Slice, resample, and normalise market data in a broker-independent way.
  - Reuse the same data preparation logic across backtest, optimisation, tests.

P1 FIX (2026-04-11) — df property was copying on every access
==============================================================
The ``df`` property previously returned ``self.data.copy()``. This means:

  - Every call to ``feed.df`` allocates a full DataFrame copy.
  - In the backtester engine: ``strategy.generate_signals(feed.df)``
    is called once per ``engine.run()`` — one copy per backtest.
  - In the optimizer walk-forward loop: ``strategy.generate_signals(feed.df)``
    is called once per window × once per parameter combo — potentially
    thousands of copies of a 750-row, 30-column DataFrame.
  - 1000 calls × ~1.8 MB per copy = ~1.8 GB of transient allocations.

Fix: ``df`` now returns ``self.data`` directly (no copy). This is safe
because:
  1. The engine already calls ``strategy.generate_signals(feed.df)`` and
     strategies start with ``df = self._validate_and_prepare(df)`` which
     does its own ``df.copy()`` — so mutations by the strategy never
     reach ``self.data``.
  2. ``between()``, ``tail()``, and ``resample()`` create new
     ``BacktestDataFeed`` instances with new ``data`` attributes — they
     do not mutate the original.
  3. ``to_dataframe()`` previously aliased ``self.df`` (which copied);
     it now explicitly returns ``self.data.copy()`` to preserve the
     behaviour for any callers that expected a fresh copy for mutation.

CONTRACT for callers:
  - Do NOT mutate the DataFrame returned by ``feed.df`` in-place.
  - If you need a mutable copy, call ``feed.df.copy()`` explicitly.
  - ``feed.to_dataframe()`` continues to return a copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class BacktestDataFeed:
    """
    Validated OHLCV wrapper used by the backtester.

    The class stays intentionally thin: it owns one normalised DataFrame
    and exposes common data-layer helpers needed by the backtest engine.
    """

    data: pd.DataFrame
    symbol: str = "SYMBOL"
    timeframe: str = ""

    def __post_init__(self) -> None:
        self.symbol    = self.symbol.strip().upper() or "SYMBOL"
        self.timeframe = self.timeframe.strip()
        self.data      = self._normalize(self.data)

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("BacktestDataFeed requires a pandas DataFrame.")
        if df.empty:
            raise ValueError("BacktestDataFeed received an empty DataFrame.")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("BacktestDataFeed requires a DatetimeIndex.")

        required = ["open", "high", "low", "close", "volume"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"DataFrame missing required OHLCV columns: {missing}")

        normalized = df.copy()
        if not normalized.index.is_monotonic_increasing:
            normalized = normalized.sort_index()
        if normalized.index.has_duplicates:
            normalized = normalized[~normalized.index.duplicated(keep="last")]

        numeric_cols = [col for col in required if col in normalized.columns]
        normalized[numeric_cols] = normalized[numeric_cols].apply(
            pd.to_numeric, errors="coerce"
        )
        normalized = normalized.dropna(subset=["open", "high", "low", "close"])
        if normalized.empty:
            raise ValueError("DataFrame contains no valid OHLC rows after normalization.")
        return normalized

    @property
    def df(self) -> pd.DataFrame:
        """
        Return the validated OHLCV DataFrame.

        P1 FIX: Returns ``self.data`` directly — no copy on every access.
        The internal ``self.data`` is set once in ``__post_init__`` and
        is never mutated by this class.

        CONTRACT: Do not mutate the returned DataFrame in-place.
        Call ``feed.df.copy()`` if you need a mutable copy.
        The backtester engine already copies via
        ``strategy._validate_and_prepare(df)`` before modifying.
        """
        return self.data

    @property
    def start(self):
        return self.data.index[0]

    @property
    def end(self):
        return self.data.index[-1]

    def between(
        self,
        start: Optional[str | pd.Timestamp] = None,
        end:   Optional[str | pd.Timestamp] = None,
    ) -> "BacktestDataFeed":
        sliced = self.data
        if start is not None:
            sliced = sliced.loc[pd.Timestamp(start):]
        if end is not None:
            sliced = sliced.loc[:pd.Timestamp(end)]
        return BacktestDataFeed(sliced, symbol=self.symbol, timeframe=self.timeframe)

    def tail(self, n: int) -> "BacktestDataFeed":
        if n <= 0:
            raise ValueError("tail length must be > 0")
        return BacktestDataFeed(
            self.data.tail(n), symbol=self.symbol, timeframe=self.timeframe
        )

    def resample(self, rule: str) -> "BacktestDataFeed":
        if not rule or not isinstance(rule, str):
            raise ValueError("resample rule must be a non-empty string")
        frame = self.data.resample(rule).agg(
            {
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
                **({"oi": "last"} if "oi" in self.data.columns else {}),
            }
        ).dropna(subset=["open", "high", "low", "close"])
        return BacktestDataFeed(frame, symbol=self.symbol, timeframe=rule)

    def to_dataframe(self) -> pd.DataFrame:
        """
        Return a mutable copy of the data suitable for external use.

        Unlike ``feed.df``, this always returns a copy so callers that
        modify the result do not affect the feed's internal state.
        """
        return self.data.copy()


__all__ = ["BacktestDataFeed"]