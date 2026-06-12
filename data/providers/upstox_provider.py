"""
data/providers/upstox_provider.py
=================================
Data provider backed by the Upstox V3 Historical API.

Calls the Upstox API directly — does NOT delegate to
``broker.upstox.data_manager.get_ohlcv`` (which has its own caching
in the legacy flat folder structure).  This ensures data is saved
*only* in the new hierarchical structure managed by ``DataManager``.

API-calling utilities (chunk generation, instrument key resolution,
candle-to-DataFrame conversion) are imported from the existing
``broker.upstox.data_manager`` module to avoid code duplication.

Authentication
--------------
Upstox historical data is free and works with a dummy token.
Live/streaming data requires real OAuth credentials.

Usage
-----
    from data.providers.upstox_provider import UpstoxProvider

    provider = UpstoxProvider()
    result = provider.fetch_ohlcv(
        "RELIANCE",
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        interval="daily",
        exchange="NSE",
        instrument_type="equity",
    )
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

import pandas as pd

from data.base import DataProviderBase, FetchResult, OHLCV_DTYPES

logger = logging.getLogger(__name__)

__all__ = ["UpstoxProvider"]

# ── Interval mapping: canonical → Upstox storage unit ────────────────────────
# The provider always fetches base resolution (interval=1) and lets
# DataManager resample.  This map translates the canonical interval
# into the Upstox "storage_unit" used for API calls and chunking.

_INTERVAL_TO_STORAGE: dict[str, str] = {
    # Intraday intervals → fetch 1-minute base data
    "1m": "minutes", "2m": "minutes", "3m": "minutes", "5m": "minutes",
    "10m": "minutes", "15m": "minutes", "30m": "minutes",
    "60m": "minutes", "1h": "minutes",
    # Daily+ intervals → fetch 1-day base data
    "daily": "days", "1d": "days",
    "weekly": "days", "1wk": "days",
    "monthly": "days", "1mo": "days",
}

# ── Instrument type mapping: canonical → Upstox ─────────────────────────────

_INSTR_TYPE_MAP: dict[str, str] = {
    "equity":  "EQUITY",
    "index":   "INDEX",
    "futures": "FUTSTK",
    "futidx":  "FUTIDX",
    "options": "OPTSTK",
    "optidx":  "OPTIDX",
}


class UpstoxProvider(DataProviderBase):
    """Upstox V3 Historical API data provider.

    Calls the Upstox API directly for raw data.  Caching is handled
    exclusively by ``DataManager`` — this provider does NOT write
    any Parquet files.

    Parameters
    ----------
    rate_limit_per_second : float
        Upstox allows 50 req/s (default uses 25 for safety headroom).
    rate_limit_per_minute : float
        Upstox allows 500 req/min.
    max_concurrent : int
        Max parallel threads for chunk downloads (default: 6).
    """

    def __init__(
        self,
        rate_limit_per_second: float = 25.0,
        rate_limit_per_minute: float = 500.0,
        max_concurrent: int = 6,
    ) -> None:
        super().__init__(
            rate_limit_per_second=rate_limit_per_second,
            rate_limit_per_minute=rate_limit_per_minute,
            max_concurrent=max_concurrent,
        )

    def get_provider_name(self) -> str:
        return "upstox"

    def get_supported_intervals(self) -> list[str]:
        return list(_INTERVAL_TO_STORAGE.keys())

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
        """Fetch OHLCV directly from the Upstox V3 API.

        Does NOT cache — ``DataManager`` handles all Parquet I/O.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. ``"RELIANCE"``).
        start, end : date
            Inclusive date range.
        interval : str
            Candle interval (see ``get_supported_intervals()``).
        exchange : str
            ``"NSE"``, ``"BSE"``, or ``"MCX"``.
        instrument_type : str
            ``"equity"``, ``"index"``, ``"futures"``, ``"options"``, etc.
        **kwargs :
            Upstox-specific: ``expiry``, ``strike``, ``option_type``.

        Returns
        -------
        FetchResult
        """
        # Resolve storage unit
        storage_unit = _INTERVAL_TO_STORAGE.get(interval.lower().strip())
        if storage_unit is None:
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=False,
                error=f"Unsupported interval: {interval!r}. "
                      f"Supported: {list(_INTERVAL_TO_STORAGE.keys())}",
            )

        # Map instrument type
        upstox_instr = _INSTR_TYPE_MAP.get(
            instrument_type.lower().strip(),
            instrument_type.upper(),
        )

        try:
            # Lazy imports — keeps Upstox SDK optional
            from broker.upstox.instrument_manager import get_instrument_key
            from broker.upstox.data_manager import (
                _get_api_instance,
                _generate_chunks,
                _fetch_one_chunk,
                _candles_to_dataframe,
            )
        except ImportError as exc:
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=False,
                error=(
                    f"Upstox SDK import failed: {exc}. "
                    "Install with: pip install upstox-python-sdk"
                ),
            )

        # Step 1: Resolve instrument key
        instrument_key = get_instrument_key(
            instrument_type=upstox_instr,
            exchange=exchange.upper(),
            trading_symbol=symbol.strip().upper(),
            option_type=kwargs.get("option_type"),
            expiry=kwargs.get("expiry"),
            strike=kwargs.get("strike"),
        )
        if not instrument_key:
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=False,
                error=(
                    f"Could not resolve Upstox instrument key for: "
                    f"{upstox_instr} {exchange} {symbol} "
                    f"expiry={kwargs.get('expiry')} "
                    f"strike={kwargs.get('strike')}"
                ),
            )

        logger.info(
            "Upstox fetch: %s | %s | %s → %s | key=%s",
            symbol, storage_unit, start, end, instrument_key,
        )

        # Step 2: Generate date chunks
        chunks = _generate_chunks(start, end, storage_unit)
        total = len(chunks)
        if total == 0:
            return FetchResult(df=pd.DataFrame(), symbol=symbol, success=True)

        # Step 3: Fetch all chunks concurrently with rate limiting
        chunk_results: list[tuple[int, pd.DataFrame]] = []
        workers = min(self._max_concurrent, total)

        def _fetch_task(
            idx: int, c_start: date, c_end: date,
        ) -> tuple[int, pd.DataFrame]:
            """Worker: rate-limit → API call → DataFrame."""
            self._limiter.acquire()
            raw_candles = _fetch_one_chunk(
                instrument_key=instrument_key,
                storage_unit=storage_unit,
                chunk_start=c_start,
                chunk_end=c_end,
            )
            if raw_candles:
                return (idx, _candles_to_dataframe(raw_candles))
            return (idx, pd.DataFrame())

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_fetch_task, i, cs, ce): i
                    for i, (cs, ce) in enumerate(chunks, start=1)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        chunk_results.append(future.result())
                    except Exception as exc:
                        logger.error(
                            "Upstox chunk %d/%d failed for %s: %s",
                            idx, total, symbol, exc,
                        )

            # Combine all non-empty DataFrames
            non_empty = [
                df for _, df in sorted(chunk_results) if not df.empty
            ]
            if not non_empty:
                logger.warning(
                    "Upstox returned no data for %s (%s → %s)",
                    symbol, start, end,
                )
                return FetchResult(
                    df=pd.DataFrame(), symbol=symbol, success=True,
                )

            combined = pd.concat(non_empty).sort_index()
            combined = self._standardise(combined)

            logger.info(
                "Fetched %d rows for %s via Upstox (%s → %s)",
                len(combined), symbol,
                combined.index.min(), combined.index.max(),
            )

            return FetchResult(
                df=combined,
                symbol=symbol,
                success=True,
                metadata={"instrument_key": instrument_key},
            )

        except Exception as exc:
            logger.error(
                "Upstox fetch failed for %s: %s (%s)",
                symbol, type(exc).__name__, exc,
            )
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=False,
                error=f"Upstox API error: {exc}",
            )

    def fetch_instrument_list(self, exchange: str = "NSE") -> pd.DataFrame:
        """Return the Upstox instrument master list."""
        try:
            from broker.upstox.instrument_manager import (
                load_instrument_master,
            )
            return load_instrument_master(exchange=exchange)
        except ImportError:
            logger.warning("Upstox SDK not available for instrument list")
            return pd.DataFrame()
        except Exception as exc:
            logger.error("Failed to load instrument list: %s", exc)
            return pd.DataFrame()

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _standardise(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure the raw API output matches canonical OHLCV schema."""
        if df.empty:
            return df

        df.index.name = "timestamp"

        if "oi" not in df.columns:
            df["oi"] = 0

        # Re-apply compact dtypes (API data may come as float64)
        for col, dtype in OHLCV_DTYPES.items():
            if col in df.columns:
                try:
                    df[col] = df[col].astype(dtype)
                except (ValueError, TypeError):
                    pass

        return df.sort_index()
