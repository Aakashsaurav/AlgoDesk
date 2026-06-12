"""
data/base.py
============
Abstract base class for all data providers in AlgoDesk.

Every concrete provider (Upstox, yfinance, etc.) must subclass
``DataProviderBase`` and implement the abstract methods.  The base
class standardises the OHLCV schema, enforces rate limiting, and
provides bulk-download orchestration via ``fetch_bulk_ohlcv``.

Design
------
*  Providers fetch raw data and return it in a canonical schema.
*  Caching, resampling, and file I/O are handled by ``DataManager`` —
   providers know nothing about Parquet.
*  Rate limiting is enforced at the provider level so that every call
   site benefits automatically.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

import pandas as pd

from data.rate_limiter import (
    CompositeRateLimiter,
    TokenBucketRateLimiter,
    create_rate_limiter,
)

logger = logging.getLogger(__name__)

__all__ = ["DataProviderBase", "OHLCVSchema", "FetchResult"]

# ── Canonical OHLCV column spec ─────────────────────────────────────────────

OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "oi")

OHLCV_DTYPES: dict[str, str] = {
    "open":   "float32",
    "high":   "float32",
    "low":    "float32",
    "close":  "float32",
    "volume": "int32",
    "oi":     "int32",
}


@dataclass(frozen=True, slots=True)
class OHLCVSchema:
    """Describes the expected output schema of every provider."""

    columns: tuple[str, ...] = OHLCV_COLUMNS
    index_name: str = "timestamp"
    index_tz: str = "Asia/Kolkata"
    dtypes: dict[str, str] = field(default_factory=lambda: dict(OHLCV_DTYPES))


# ── Fetch result wrapper ────────────────────────────────────────────────────

@dataclass(slots=True)
class FetchResult:
    """Container returned by ``fetch_ohlcv``.

    Attributes
    ----------
    df : pd.DataFrame
        OHLCV data (may be empty on error).
    symbol : str
        Requested symbol.
    success : bool
        Whether the fetch completed without error.
    error : str
        Error message if ``success`` is False.
    metadata : dict
        Provider-specific metadata (e.g. instrument_key).
    """

    df: pd.DataFrame
    symbol: str
    success: bool = True
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Abstract base ───────────────────────────────────────────────────────────

class DataProviderBase(ABC):
    """Abstract base for all data providers.

    Subclasses **must** implement:

    *  ``fetch_ohlcv``
    *  ``get_supported_intervals``
    *  ``get_provider_name``

    And **may** override:

    *  ``fetch_instrument_list``

    Parameters
    ----------
    rate_limit_per_second : float
        Max requests/second this provider allows (default 5).
    rate_limit_per_minute : float | None
        Optional per-minute cap.
    max_concurrent : int
        Max parallel downloads for ``fetch_bulk_ohlcv`` (default 4).
    """

    SCHEMA: OHLCVSchema = OHLCVSchema()

    def __init__(
        self,
        rate_limit_per_second: float = 5.0,
        rate_limit_per_minute: float | None = None,
        max_concurrent: int = 4,
    ) -> None:
        self._max_concurrent: int = max(1, max_concurrent)
        self._limiter: TokenBucketRateLimiter | CompositeRateLimiter = (
            create_rate_limiter(rate_limit_per_second, rate_limit_per_minute)
        )
        logger.info(
            "%s initialised — rate_limit=%s, max_concurrent=%d",
            self.get_provider_name(),
            self._limiter,
            self._max_concurrent,
        )

    # ── Abstract interface ────────────────────────────────────────────

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "daily",
        exchange: str = "NSE",
        instrument_type: str = "equity",
        **kwargs: Any,
    ) -> FetchResult:
        """Fetch OHLCV data for a single symbol.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. ``"RELIANCE"``).
        start, end : date
            Inclusive date range.
        interval : str
            One of ``get_supported_intervals()``.
        exchange : str
            Exchange code (``"NSE"``, ``"BSE"``).
        instrument_type : str
            ``"equity"``, ``"futures"``, ``"options"``, etc.
        **kwargs :
            Provider-specific arguments (e.g. ``expiry``, ``strike``).

        Returns
        -------
        FetchResult
            With ``df`` in canonical OHLCV schema.
        """

    @abstractmethod
    def get_supported_intervals(self) -> list[str]:
        """Return list of supported interval strings.

        Example: ``["1m", "5m", "15m", "1h", "daily", "weekly"]``
        """

    @abstractmethod
    def get_provider_name(self) -> str:
        """Human-readable provider name (e.g. ``"yfinance"``)."""

    # ── Optional overrides ────────────────────────────────────────────

    def fetch_instrument_list(
        self,
        exchange: str = "NSE",
    ) -> pd.DataFrame:
        """Return available instruments on the exchange.

        Default implementation returns an empty DataFrame.  Override in
        providers that support instrument discovery.
        """
        logger.warning(
            "%s does not implement fetch_instrument_list",
            self.get_provider_name(),
        )
        return pd.DataFrame()

    # ── Rate-limited fetch helper ─────────────────────────────────────

    def _rate_limited_fetch(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "daily",
        exchange: str = "NSE",
        instrument_type: str = "equity",
        **kwargs: Any,
    ) -> FetchResult:
        """Acquire a rate-limit token, then delegate to ``fetch_ohlcv``."""
        self._limiter.acquire()
        return self.fetch_ohlcv(
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            exchange=exchange,
            instrument_type=instrument_type,
            **kwargs,
        )

    # ── Bulk download with parallel + rate-limiting ───────────────────

    def fetch_bulk_ohlcv(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        interval: str = "daily",
        exchange: str = "NSE",
        instrument_type: str = "equity",
        **kwargs: Any,
    ) -> list[FetchResult]:
        """Download OHLCV for multiple symbols in parallel.

        Uses a thread pool capped at ``max_concurrent`` workers.
        Each worker acquires a rate-limit token before calling the API,
        so throughput is maximised without exceeding provider limits.

        Parameters
        ----------
        symbols : sequence of str
            Trading symbols to fetch.
        start, end : date
            Inclusive date range.
        interval, exchange, instrument_type :
            Passed through to ``fetch_ohlcv``.

        Returns
        -------
        list[FetchResult]
            One result per symbol, in the same order as *symbols*.
        """
        total = len(symbols)
        if total == 0:
            return []

        logger.info(
            "Bulk fetch: %d symbols via %s (%s, %s → %s)",
            total,
            self.get_provider_name(),
            interval,
            start,
            end,
        )

        # Map future → index for ordered results
        results: list[FetchResult | None] = [None] * total
        workers = min(self._max_concurrent, total)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(
                    self._rate_limited_fetch,
                    symbol=sym,
                    start=start,
                    end=end,
                    interval=interval,
                    exchange=exchange,
                    instrument_type=instrument_type,
                    **kwargs,
                ): idx
                for idx, sym in enumerate(symbols)
            }

            completed = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                completed += 1
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    results[idx] = FetchResult(
                        df=pd.DataFrame(),
                        symbol=symbols[idx],
                        success=False,
                        error=str(exc),
                    )
                    logger.error(
                        "Bulk fetch [%d/%d] %s failed: %s",
                        completed,
                        total,
                        symbols[idx],
                        exc,
                    )

                # Progress logging every 10% or every 50 symbols
                if completed % max(1, total // 10) == 0:
                    logger.info("Bulk fetch progress: %d/%d", completed, total)

        logger.info("Bulk fetch complete: %d/%d succeeded", 
                     sum(1 for r in results if r and r.success), total)
        return results  # type: ignore[return-value]

    # ── Schema enforcement helper ─────────────────────────────────────

    @staticmethod
    def enforce_schema(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce a DataFrame to the canonical OHLCV schema.

        *  Ensures required columns exist (fills ``oi`` with 0 if absent).
        *  Applies compact dtypes (float32 / int32).
        *  Sets index name to ``"timestamp"``.
        *  Sorts by index.

        Parameters
        ----------
        df : pd.DataFrame
            Raw OHLCV data (index must be DatetimeIndex).

        Returns
        -------
        pd.DataFrame
            Schema-conformant DataFrame.
        """
        if df.empty:
            return df

        # Ensure 'oi' column exists
        if "oi" not in df.columns:
            df["oi"] = 0

        # Keep only canonical columns (+ preserve any extras the caller wants)
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col!r}")

        # Apply compact dtypes
        for col, dtype in OHLCV_DTYPES.items():
            if col in df.columns:
                df[col] = df[col].astype(dtype)

        df.index.name = "timestamp"
        df = df.sort_index()
        return df
