"""
data/manager.py
===============
Unified data manager for AlgoDesk.

Orchestrates data fetching (via any ``DataProviderBase``), Parquet
caching with the new hierarchical folder structure, incremental
updates, multi-timeframe resampling, and bulk downloads.

Key behaviours
--------------
1. **Cache-first**: Never hits the API if the cache already covers the
   requested date range (even if data was originally from a different
   provider).
2. **Incremental updates**: Only fetches the missing tail when the
   cache is stale — doesn't re-download the entire history.
3. **Provider fallback**: On failure, automatically tries fallback
   providers (e.g. Upstox fails → try yfinance).
4. **Single storage location**: All data goes into the new
   hierarchical Parquet structure. No dual-write.

Folder structure
----------------
::

    data/ohlcv/<exchange>/<instrument_type>/<timeframe>/<symbol>/
        daily  : <SYMBOL>.parquet       (single file, all history)
        minute : <YYYY-MM>.parquet      (monthly chunks)
        weekly : <SYMBOL>.parquet       (single file)

Usage
-----
    from data.manager import DataManager
    from data.providers.yfinance_provider import YFinanceProvider
    from data.providers.upstox_provider import UpstoxProvider

    mgr = DataManager(
        provider=UpstoxProvider(),
        fallback_providers=[YFinanceProvider()],
    )
    df = mgr.fetch("RELIANCE", interval="daily")
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pq = None

from config import config
from data.base import DataProviderBase, FetchResult, OHLCV_DTYPES

logger = logging.getLogger(__name__)

__all__ = ["DataManager"]

_IST_TZ = ZoneInfo("Asia/Kolkata")

# ── Storage resolution mapping ───────────────────────────────────────────────

_STORAGE_TIMEFRAME: dict[str, str] = {
    "1m": "minute", "2m": "minute", "3m": "minute", "5m": "minute",
    "10m": "minute", "15m": "minute", "30m": "minute",
    "60m": "minute", "1h": "minute",
    "daily": "daily", "1d": "daily",
    "weekly": "weekly", "1wk": "weekly",
    "monthly": "daily",  # resampled from daily
    "1mo": "daily",
}

_STORAGE_INTERVAL: dict[str, str] = {
    "minute": "1m",
    "daily":  "daily",
    "weekly": "weekly",
}

_RESAMPLE_FREQ: dict[str, str] = {
    "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min",
    "10m": "10min", "15m": "15min", "30m": "30min",
    "60m": "1h", "1h": "1h",
    "daily": "1B", "1d": "1B",
    "weekly": "1W", "1wk": "1W",
    "monthly": "1ME", "1mo": "1ME",
}
# Earliest dates we can request data for (limits)
MINUTE_DATA_START = date(2022, 1, 3)
DAY_DATA_START = date(2000, 1, 3)


class DataManager:
    """Unified data cache and fetch orchestrator.

    Parameters
    ----------
    provider : DataProviderBase
        Primary data provider.
    fallback_providers : list[DataProviderBase] | None
        Providers to try (in order) when the primary fails.
    ohlcv_dir : Path | None
        Root directory for Parquet storage.
        Defaults to ``config.OHLCV_DIR`` (``data/ohlcv/``).
    """

    def __init__(
        self,
        provider: DataProviderBase,
        fallback_providers: list[DataProviderBase] | None = None,
        ohlcv_dir: Path | None = None,
    ) -> None:
        self._provider: DataProviderBase = provider
        self._fallback_providers: list[DataProviderBase] = (
            fallback_providers or []
        )
        self._ohlcv_dir: Path = ohlcv_dir or config.OHLCV_DIR

    @property
    def provider_name(self) -> str:
        return self._provider.get_provider_name()

    # ══════════════════════════════════════════════════════════════════
    # Core API
    # ══════════════════════════════════════════════════════════════════

    def fetch(
        self,
        symbol: str,
        interval: str = "daily",
        start: date | None = None,
        end: date | None = None,
        period: str | None = None,
        exchange: str = "NSE",
        instrument_type: str = "equity",
        use_cache: bool = True,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch OHLCV data with cache-first logic and provider fallback.

        Flow
        ----
        1. Check cache — if data covers the requested range, return it
           immediately (no API call, regardless of which provider
           originally fetched it).
        2. If cache is partially stale, compute the missing tail and
           fetch only the incremental data.
        3. If primary provider fails, try each fallback provider.
        4. Merge new data into cache (deduplicate, sort).
        5. Resample to the requested interval and return.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. ``"RELIANCE"``).
        interval : str
            Candle interval: ``"1m"`` through ``"monthly"``.
        start, end : date | None
            Date range.  If *period* is given, *start* is computed
            from *end* (which defaults to today).
        period : str | None
            Human-readable period (e.g. ``"3months"``, ``"1year"``).
        exchange : str
            ``"NSE"`` or ``"BSE"``.
        instrument_type : str
            ``"equity"``, ``"futures"``, ``"options"``, etc.
        use_cache : bool
            If True, read from / write to Parquet cache.
        **kwargs :
            Provider-specific arguments.

        Returns
        -------
        pd.DataFrame
            OHLCV data in canonical schema.
        """
        symbol = symbol.strip().upper()
        interval = interval.lower().strip()

        # Resolve date range
        start, end = self._resolve_dates(start, end, period)

        # Determine storage resolution
        timeframe = _STORAGE_TIMEFRAME.get(interval)
        if timeframe is None:
            raise ValueError(
                f"Unsupported interval: {interval!r}. "
                f"Supported: {list(_STORAGE_TIMEFRAME.keys())}"
            )

        storage_interval = _STORAGE_INTERVAL[timeframe]
        cache_dir = self._cache_path(
            exchange, instrument_type, timeframe, symbol,
        )

        # ── Step 1: Identify missing date ranges in cache ──────────────
        fetch_ranges: list[tuple[date, date]] = []
        
        if use_cache:
            latest_cached = self._get_latest_cached_date(cache_dir, timeframe, symbol)
            earliest_cached = self._get_earliest_cached_date(cache_dir, timeframe, symbol)
            
            if latest_cached is not None and earliest_cached is not None:
                # 1. Check if older data is missing
                abs_start = MINUTE_DATA_START if timeframe == "minute" else DAY_DATA_START
                if start < earliest_cached - timedelta(days=5) and earliest_cached > abs_start + timedelta(days=5):
                    fetch_ranges.append((start, earliest_cached - timedelta(days=1)))
                
                # 2. Check if newer data is missing
                if not self._cache_is_current(latest_cached, timeframe):
                    fetch_ranges.append((latest_cached + timedelta(days=1), end))
                
                if not fetch_ranges:
                    logger.info(
                        "Cache is current and covers the requested range for %s (%s). "
                        "No API call needed.",
                        symbol, timeframe,
                    )
                    cached_df = self._read_cache(cache_dir, timeframe, start, end)
                    if not cached_df.empty:
                        if interval != storage_interval:
                            cached_df = self._resample(cached_df, interval)
                        return self._filter_date_range(cached_df, start, end)
            else:
                # No cache at all
                fetch_ranges.append((start, end))
                logger.info(
                    "No cache for %s (%s). Downloading: %s → %s",
                    symbol, timeframe, start, end,
                )
        else:
            fetch_ranges.append((start, end))

        # ── Step 2: Fetch and merge missing ranges ─────────────────────
        any_new_data = False
        last_result = None
        for f_start, f_end in fetch_ranges:
            if f_start > f_end:
                continue
                
            logger.info(
                "Fetching missing range for %s (%s): %s → %s",
                symbol, timeframe, f_start, f_end,
            )
            result = self._fetch_with_fallback(
                symbol=symbol,
                start=f_start,
                end=f_end,
                interval=storage_interval,
                exchange=exchange,
                instrument_type=instrument_type,
                **kwargs,
            )
            if result is not None and not result.df.empty:
                any_new_data = True
                last_result = result
                if use_cache:
                    self._write_cache(result.df, cache_dir, timeframe, symbol)

        # ── Step 3: Load the full range from cache (or the last result)
        if use_cache:
            full_df = self._read_cache(cache_dir, timeframe, start, end)
        else:
            full_df = last_result.df if last_result is not None else pd.DataFrame()

        if full_df.empty:
            # Try returning whatever is in cache, even if stale
            if use_cache:
                cached_df = self._read_cache(cache_dir, timeframe, start, end)
                if not cached_df.empty:
                    logger.info(
                        "API returned no new data for %s. Returning cached data.",
                        symbol,
                    )
                    if interval != storage_interval:
                        cached_df = self._resample(cached_df, interval)
                    return self._filter_date_range(cached_df, start, end)
            return pd.DataFrame()

        # ── Step 4: Resample and filter ───────────────────────────────
        if interval != storage_interval:
            full_df = self._resample(full_df, interval)

        return self._filter_date_range(full_df, start, end)

    def fetch_bulk(
        self,
        symbols: Sequence[str],
        interval: str = "daily",
        start: date | None = None,
        end: date | None = None,
        period: str | None = None,
        exchange: str = "NSE",
        instrument_type: str = "equity",
        use_cache: bool = True,
        **kwargs: Any,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols.

        Each symbol goes through the full cache-check → fetch →
        fallback pipeline individually.

        Returns
        -------
        dict[str, pd.DataFrame]
            Keyed by symbol.
        """
        start, end = self._resolve_dates(start, end, period)
        results: dict[str, pd.DataFrame] = {}

        total = len(symbols)
        for i, sym in enumerate(symbols, 1):
            logger.info("Bulk fetch [%d/%d]: %s", i, total, sym)
            df = self.fetch(
                symbol=sym,
                interval=interval,
                start=start,
                end=end,
                exchange=exchange,
                instrument_type=instrument_type,
                use_cache=use_cache,
                **kwargs,
            )
            results[sym.strip().upper()] = df

        successes = sum(1 for df in results.values() if not df.empty)
        logger.info(
            "Bulk fetch complete: %d/%d symbols have data",
            successes, total,
        )
        return results

    # ══════════════════════════════════════════════════════════════════
    # Provider fallback
    # ══════════════════════════════════════════════════════════════════

    def _fetch_with_fallback(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str,
        exchange: str,
        instrument_type: str,
        **kwargs: Any,
    ) -> FetchResult | None:
        """Try the primary provider, then fallback providers for any missing date ranges on partial success.

        Logs the failure reason from each provider.
        """
        all_providers = [self._provider] + self._fallback_providers
        combined_df = pd.DataFrame()
        errors: list[str] = []
        metadata: dict[str, Any] = {}
        any_success = False

        current_start = start
        current_end = end

        for provider in all_providers:
            if current_start > current_end:
                break

            name = provider.get_provider_name()
            logger.info(
                "Attempting fetch via %s: %s %s %s → %s",
                name, symbol, interval, current_start, current_end,
            )

            try:
                result = provider.fetch_ohlcv(
                    symbol=symbol,
                    start=current_start,
                    end=current_end,
                    interval=interval,
                    exchange=exchange,
                    instrument_type=instrument_type,
                    **kwargs,
                )

                if result.success and not result.df.empty:
                    any_success = True
                    logger.info(
                        "✓ %s: %d rows for %s",
                        name, len(result.df), symbol,
                    )
                    
                    if combined_df.empty:
                        combined_df = result.df
                    else:
                        combined_df = pd.concat([combined_df, result.df])
                        combined_df = combined_df[~combined_df.index.duplicated(keep="last")]
                    
                    if result.metadata:
                        metadata[name] = result.metadata

                    actual_start = result.df.index.min().date()
                    if actual_start > current_start + timedelta(days=5):
                        current_end = actual_start - timedelta(days=1)
                        logger.info(
                            "%s returned partial data. Still missing older range: %s → %s. "
                            "Will attempt fallback for this remaining period.",
                            name, current_start, current_end
                        )
                    else:
                        current_start = current_end + timedelta(days=1)
                        break

                elif not result.success:
                    logger.warning(
                        "✗ %s failed for %s — reason: %s",
                        name, symbol, result.error,
                    )
                    if result.error:
                        errors.append(f"{name}: {result.error}")
                else:
                    logger.info(
                        "✗ %s returned no data for %s "
                        "(not an error — may be holiday/weekend)",
                        name, symbol,
                    )

            except Exception as exc:
                logger.error(
                    "✗ %s raised exception for %s: %s (%s)",
                    name, symbol, type(exc).__name__, exc,
                )
                errors.append(f"{name}: {type(exc).__name__} ({exc})")

        if any_success:
            combined_df = combined_df.sort_index()
            return FetchResult(
                df=combined_df,
                symbol=symbol,
                success=True,
                error="; ".join(errors) if errors else "",
                metadata=metadata,
            )

        logger.error(
            "All providers failed for %s. Providers tried: %s",
            symbol,
            [p.get_provider_name() for p in all_providers],
        )
        return None

    # ══════════════════════════════════════════════════════════════════
    # Cache freshness (ported from broker/upstox/data_manager.py)
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _last_trading_day(reference: date | None = None) -> date:
        """Return the most recent trading day on or before *reference*.

        Rolls Saturday → Friday, Sunday → Friday.  NSE holidays are
        not hardcoded — the API simply returns empty for those days,
        which is handled gracefully.
        """
        d = reference or date.today()
        while d.weekday() >= 5:  # 5=Sat, 6=Sun
            d -= timedelta(days=1)
        return d

    @classmethod
    def _cache_is_current(
        cls,
        latest_cached: date,
        timeframe: str,
    ) -> bool:
        """Return True if the cache is up-to-date.

        Logic (mirrored from broker/upstox/data_manager):
        - For daily: cache is current if latest_cached >= last trading day.
        - For minute: also checks that market has closed (15:35 IST).
        """
        from datetime import datetime

        last_trade_day = cls._last_trading_day(date.today())

        if timeframe in ("daily", "weekly"):
            return latest_cached >= last_trade_day

        if timeframe == "minute":
            now_ist = datetime.now(tz=_IST_TZ)
            mkt_close = now_ist.replace(
                hour=15, minute=35, second=0, microsecond=0,
            )
            if now_ist.weekday() < 5 and now_ist < mkt_close:
                # Market still open — last *complete* day is yesterday
                last_complete = cls._last_trading_day(
                    now_ist.date() - timedelta(days=1),
                )
            else:
                last_complete = last_trade_day
            return latest_cached >= last_complete

        return False

    def _get_latest_cached_date(
        self,
        cache_dir: Path,
        timeframe: str,
        symbol: str,
    ) -> date | None:
        """Inspect Parquet files and return the latest cached date.

        Uses PyArrow metadata (zero-row read) when available; falls
        back to a minimal pandas read otherwise.
        """
        if not cache_dir.exists():
            return None

        if timeframe == "minute":
            parquet_files = sorted(cache_dir.glob("*.parquet"))
            if not parquet_files:
                return None
            return self._max_date_from_parquet(parquet_files[-1])

        else:
            fpath = cache_dir / f"{symbol}.parquet"
            if not fpath.exists():
                return None
            return self._max_date_from_parquet(fpath)

    @staticmethod
    def _max_date_from_parquet(file_path: Path) -> date | None:
        """Extract the max timestamp date from a Parquet file cheaply.

        Fast path: PyArrow row-group statistics (zero data read).
        Slow path: minimal pandas column read.
        """
        # Fast path: PyArrow metadata
        if pq is not None:
            try:
                pf = pq.ParquetFile(file_path)
                schema = pf.schema_arrow
                ts_col_idx = None
                for i in range(len(schema)):
                    if schema.field(i).name == "timestamp":
                        ts_col_idx = i
                        break

                if ts_col_idx is not None:
                    max_ts = None
                    for rg_idx in range(pf.metadata.num_row_groups):
                        rg = pf.metadata.row_group(rg_idx)
                        col = rg.column(ts_col_idx)
                        if col.statistics and col.statistics.has_min_max:
                            rg_max = col.statistics.max
                            if max_ts is None or rg_max > max_ts:
                                max_ts = rg_max
                    if max_ts is not None:
                        if hasattr(max_ts, "tzinfo") and max_ts.tzinfo is not None:
                            max_ts = max_ts.astimezone(_IST_TZ)
                        if hasattr(max_ts, "date"):
                            return max_ts.date()
                        return max_ts
            except Exception:
                pass  # fall through to pandas

        # Slow fallback
        try:
            df = pd.read_parquet(file_path, columns=["open"])
            if df.empty:
                return None
            return df.index.max().date()
        except Exception as exc:
            logger.warning(
                "Could not read %s: %s. Treating as no cache.", file_path, exc,
            )
            return None

    def _get_earliest_cached_date(
        self,
        cache_dir: Path,
        timeframe: str,
        symbol: str,
    ) -> date | None:
        """Inspect Parquet files and return the earliest cached date.

        Uses PyArrow metadata (zero-row read) when available; falls
        back to a minimal pandas read otherwise.
        """
        if not cache_dir.exists():
            return None

        if timeframe == "minute":
            parquet_files = sorted(cache_dir.glob("*.parquet"))
            if not parquet_files:
                return None
            return self._min_date_from_parquet(parquet_files[0])
        else:
            fpath = cache_dir / f"{symbol}.parquet"
            if not fpath.exists():
                return None
            return self._min_date_from_parquet(fpath)

    @staticmethod
    def _min_date_from_parquet(file_path: Path) -> date | None:
        """Extract the min timestamp date from a Parquet file cheaply.

        Fast path: PyArrow row-group statistics (zero data read).
        Slow path: minimal pandas column read.
        """
        if pq is not None:
            try:
                pf = pq.ParquetFile(file_path)
                schema = pf.schema_arrow
                ts_col_idx = None
                for i in range(len(schema)):
                    if schema.field(i).name == "timestamp":
                        ts_col_idx = i
                        break

                if ts_col_idx is not None:
                    min_ts = None
                    for rg_idx in range(pf.metadata.num_row_groups):
                        rg = pf.metadata.row_group(rg_idx)
                        col = rg.column(ts_col_idx)
                        if col.statistics and col.statistics.has_min_max:
                            rg_min = col.statistics.min
                            if min_ts is None or rg_min < min_ts:
                                min_ts = rg_min
                    if min_ts is not None:
                        if hasattr(min_ts, "tzinfo") and min_ts.tzinfo is not None:
                            min_ts = min_ts.astimezone(_IST_TZ)
                        if hasattr(min_ts, "date"):
                            return min_ts.date()
                        return min_ts
            except Exception:
                pass  # fall through to pandas

        try:
            df = pd.read_parquet(file_path, columns=["open"])
            if df.empty:
                return None
            return df.index.min().date()
        except Exception as exc:
            logger.warning(
                "Could not read %s: %s. Treating as no cache.", file_path, exc,
            )
            return None

    # ══════════════════════════════════════════════════════════════════
    # Cache path construction
    # ══════════════════════════════════════════════════════════════════

    def _cache_path(
        self,
        exchange: str,
        instrument_type: str,
        timeframe: str,
        symbol: str,
    ) -> Path:
        """Build: ohlcv/<exchange>/<instrument_type>/<timeframe>/<symbol>/"""
        return (
            self._ohlcv_dir
            / exchange.upper()
            / instrument_type.lower()
            / timeframe
            / symbol.upper()
        )

    # ══════════════════════════════════════════════════════════════════
    # Cache read
    # ══════════════════════════════════════════════════════════════════

    def _read_cache(
        self,
        cache_dir: Path,
        timeframe: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Read cached Parquet files for the given date range."""
        if not cache_dir.exists():
            return pd.DataFrame()

        if timeframe == "minute":
            return self._read_minute_cache(cache_dir, start, end)
        else:
            return self._read_single_cache(cache_dir)

    def _read_minute_cache(
        self,
        cache_dir: Path,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Read monthly minute-data Parquet chunks."""
        needed: set[str] = set()
        cursor = start.replace(day=1)
        while cursor <= end:
            needed.add(f"{cursor.year}-{cursor.month:02d}")
            if cursor.month == 12:
                cursor = cursor.replace(year=cursor.year + 1, month=1)
            else:
                cursor = cursor.replace(month=cursor.month + 1)

        frames: list[pd.DataFrame] = []
        for period_str in sorted(needed):
            fpath = cache_dir / f"{period_str}.parquet"
            if fpath.exists():
                try:
                    frames.append(pd.read_parquet(fpath))
                except Exception as exc:
                    logger.warning("Failed to read %s: %s", fpath, exc)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames).sort_index()

    def _read_single_cache(self, cache_dir: Path) -> pd.DataFrame:
        """Read a single-file cache (daily/weekly)."""
        files = list(cache_dir.glob("*.parquet"))
        if not files:
            return pd.DataFrame()
        try:
            return pd.read_parquet(files[0])
        except Exception as exc:
            logger.warning("Failed to read %s: %s", files[0], exc)
            return pd.DataFrame()

    # ══════════════════════════════════════════════════════════════════
    # Cache write
    # ══════════════════════════════════════════════════════════════════

    def _write_cache(
        self,
        df: pd.DataFrame,
        cache_dir: Path,
        timeframe: str,
        symbol: str,
    ) -> None:
        """Write data to Parquet cache."""
        cache_dir.mkdir(parents=True, exist_ok=True)

        if timeframe == "minute":
            self._write_minute_cache(df, cache_dir)
        else:
            self._write_single_cache(df, cache_dir, symbol)

    def _write_minute_cache(
        self,
        df: pd.DataFrame,
        cache_dir: Path,
    ) -> None:
        """Write minute data as monthly Parquet chunks."""
        ym_labels = df.index.tz_localize(None).to_period("M")
        for period, group in df.groupby(ym_labels):
            fpath = cache_dir / f"{period}.parquet"
            merged = self._merge_with_existing(fpath, group)
            merged.to_parquet(fpath, compression="snappy", engine="pyarrow")
            logger.debug("Wrote %d rows to %s", len(merged), fpath)

    def _write_single_cache(
        self,
        df: pd.DataFrame,
        cache_dir: Path,
        symbol: str,
    ) -> None:
        """Write daily/weekly data as a single Parquet file."""
        fpath = cache_dir / f"{symbol}.parquet"
        merged = self._merge_with_existing(fpath, df)
        merged.to_parquet(fpath, compression="snappy", engine="pyarrow")
        logger.debug("Wrote %d rows to %s", len(merged), fpath)

    @staticmethod
    def _merge_with_existing(
        fpath: Path,
        new_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Merge new data with existing Parquet file.

        Deduplicates on index (new data wins), re-applies compact
        dtypes, and sorts chronologically.
        """
        if fpath.exists():
            try:
                existing = pd.read_parquet(fpath)
                merged = pd.concat([existing, new_df])
                merged = merged[~merged.index.duplicated(keep="last")]
            except Exception:
                merged = new_df
        else:
            merged = new_df

        merged = merged.sort_index()

        for col, dtype in OHLCV_DTYPES.items():
            if col in merged.columns:
                try:
                    merged[col] = merged[col].astype(dtype)
                except (ValueError, TypeError):
                    pass

        return merged

    # ══════════════════════════════════════════════════════════════════
    # Resampling
    # ══════════════════════════════════════════════════════════════════

    def _resample(
        self,
        df: pd.DataFrame,
        interval: str,
    ) -> pd.DataFrame:
        """Resample OHLCV data to the requested interval."""
        if df.empty:
            return df

        freq = _RESAMPLE_FREQ.get(interval)
        if freq is None:
            logger.warning(
                "No resample frequency for %r — returning raw", interval,
            )
            return df

        # Filter to market hours for intraday data
        if interval in (
            "1m", "2m", "3m", "5m", "10m", "15m", "30m", "60m", "1h",
        ):
            df = self._filter_market_hours(df)

        resampled = df.resample(freq).agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
            "oi":     "last",
        })

        resampled = resampled.dropna(subset=["open", "close"])

        for col, dtype in OHLCV_DTYPES.items():
            if col in resampled.columns:
                try:
                    resampled[col] = resampled[col].astype(dtype)
                except (ValueError, TypeError):
                    pass

        return resampled

    @staticmethod
    def _filter_market_hours(df: pd.DataFrame) -> pd.DataFrame:
        """Keep only bars within NSE market hours (09:15–15:30 IST)."""
        if df.empty:
            return df
        import datetime as dt

        times = df.index.time
        mkt_open = dt.time(9, 15)
        mkt_close = dt.time(15, 30)
        mask = (times >= mkt_open) & (times <= mkt_close)
        return df.loc[mask]

    # ══════════════════════════════════════════════════════════════════
    # Date range helpers
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _resolve_dates(
        start: date | None,
        end: date | None,
        period: str | None,
    ) -> tuple[date, date]:
        """Resolve start/end dates from the provided arguments."""
        today = date.today()

        if end is None:
            end = today
        if end > today:
            end = today

        if start is not None:
            if start > end:
                raise ValueError(
                    f"start ({start}) must be before end ({end})"
                )
            return start, end

        if period is not None:
            start = _period_to_date(period, end)
            return start, end

        # Default: 1 year of data
        return end - timedelta(days=365), end

    @staticmethod
    def _filter_date_range(
        df: pd.DataFrame,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Filter DataFrame to the [start, end] date range."""
        if df.empty:
            return df

        tz = df.index.tz or "Asia/Kolkata"
        ts_start = pd.Timestamp(start, tz=tz)
        ts_end = (
            pd.Timestamp(end, tz=tz)
            + pd.Timedelta(days=1)
            - pd.Timedelta(seconds=1)
        )
        return df.loc[ts_start:ts_end]

    # ══════════════════════════════════════════════════════════════════
    # Cache management
    # ══════════════════════════════════════════════════════════════════

    def clear_cache(
        self,
        symbol: str | None = None,
        exchange: str = "NSE",
        instrument_type: str = "equity",
    ) -> int:
        """Delete cached Parquet files.

        Parameters
        ----------
        symbol : str | None
            If given, clear only this symbol's cache.
            If None, clear all cached data (use with caution).

        Returns
        -------
        int
            Number of files deleted.
        """
        import shutil

        if symbol:
            count = 0
            for tf in ("daily", "minute", "weekly"):
                path = self._cache_path(exchange, instrument_type, tf, symbol)
                if path.exists():
                    n = len(list(path.glob("*.parquet")))
                    shutil.rmtree(path)
                    count += n
                    logger.info(
                        "Cleared %d files for %s/%s", n, symbol, tf,
                    )
            return count
        else:
            count = len(list(self._ohlcv_dir.rglob("*.parquet")))
            if count > 0:
                shutil.rmtree(self._ohlcv_dir)
                self._ohlcv_dir.mkdir(parents=True, exist_ok=True)
                logger.warning("Cleared entire cache: %d files", count)
            return count


# ── Period string parser ─────────────────────────────────────────────────────

def _period_to_date(period: str, reference: date) -> date:
    """Convert a human-readable period string to a start date.

    Supported: ``"3months"``, ``"90days"``, ``"2years"``, ``"4weeks"``.
    """
    import re
    import calendar

    m = re.fullmatch(
        r"(\d+)\s*(days?|weeks?|months?|years?)",
        period.strip().lower(),
    )
    if not m:
        raise ValueError(
            f"Cannot parse period {period!r}. "
            "Use: '3months', '90days', '2years', '4weeks'."
        )

    n, unit = int(m.group(1)), m.group(2)

    if unit.startswith("year"):
        try:
            return reference.replace(year=reference.year - n)
        except ValueError:
            return reference.replace(year=reference.year - n, day=28)

    if unit.startswith("month"):
        month = reference.month - n
        year = reference.year
        while month <= 0:
            month += 12
            year -= 1
        max_day = calendar.monthrange(year, month)[1]
        return reference.replace(
            year=year, month=month, day=min(reference.day, max_day),
        )

    if unit.startswith("week"):
        return reference - timedelta(weeks=n)

    if unit.startswith("day"):
        return reference - timedelta(days=n)

    raise ValueError(f"Unknown period unit in {period!r}")
