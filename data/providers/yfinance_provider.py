"""
data/providers/yfinance_provider.py
===================================
Data provider backed by the ``yfinance`` library.

Free, no authentication required.  Ideal for backtesting and research.
Supports NSE and BSE equities via Yahoo Finance's ticker format
(e.g. ``RELIANCE.NS``).

yfinance restrictions (handled automatically)
----------------------------------------------
Interval  Max lookback  Max range/call  Strategy
────────  ────────────  ──────────────  ────────────────
1m        30 days       7 days          chunk into 7-day windows
2m        60 days       60 days         single call (clamped)
5m        60 days       60 days         single call (clamped)
15m       60 days       60 days         single call (clamped)
30m       60 days       60 days         single call (clamped)
60m       730 days      730 days        single call (clamped)
1d        unlimited     unlimited       single call
1wk       unlimited     unlimited       single call
1mo       unlimited     unlimited       single call

Usage
-----
    from data.providers.yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    result = provider.fetch_ohlcv("RELIANCE", start=date(2024, 1, 1), end=date(2024, 12, 31))
    print(result.df)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from data.base import DataProviderBase, FetchResult, OHLCV_DTYPES
from data.universe import SymbolMapper

logger = logging.getLogger(__name__)

__all__ = ["YFinanceProvider"]

# ── Interval mapping: canonical → yfinance ───────────────────────────────────

_INTERVAL_MAP: dict[str, str] = {
    "1m":     "1m",
    "2m":     "2m",
    "5m":     "5m",
    "15m":    "15m",
    "30m":    "30m",
    "60m":    "60m",
    "1h":     "60m",
    "daily":  "1d",
    "1d":     "1d",
    "weekly": "1wk",
    "1wk":    "1wk",
    "monthly": "1mo",
    "1mo":    "1mo",
}

# ── yfinance restrictions per interval ───────────────────────────────────────
# (max_lookback_days, max_range_per_call_days)

_YF_LIMITS: dict[str, tuple[int, int]] = {
    "1m":  (30, 7),
    "2m":  (60, 60),
    "5m":  (60, 60),
    "15m": (60, 60),
    "30m": (60, 60),
    "60m": (730, 730),
    "1d":  (0, 0),      # 0 = unlimited
    "1wk": (0, 0),
    "1mo": (0, 0),
}


class YFinanceProvider(DataProviderBase):
    """Yahoo Finance data provider via the ``yfinance`` library.

    Parameters
    ----------
    rate_limit_per_second : float
        Max requests/second (default: 2.0 — conservative for yfinance).
    max_concurrent : int
        Max parallel downloads for ``fetch_bulk_ohlcv`` (default: 3).
    """

    def __init__(
        self,
        rate_limit_per_second: float = 2.0,
        max_concurrent: int = 3,
    ) -> None:
        super().__init__(
            rate_limit_per_second=rate_limit_per_second,
            rate_limit_per_minute=None,  # yfinance has no known per-min cap
            max_concurrent=max_concurrent,
        )
        self._mapper = SymbolMapper()
        self._yf = _lazy_import_yfinance()

    def get_provider_name(self) -> str:
        return "yfinance"

    def get_supported_intervals(self) -> list[str]:
        return ["1m", "2m", "5m", "15m", "30m", "60m", "1h",
                "daily", "1d", "weekly", "1wk", "monthly", "1mo"]

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
        """Fetch OHLCV data from Yahoo Finance.

        Automatically handles yfinance's per-interval restrictions:
        clamps lookback, chunks requests for 1m data (7-day windows).

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. ``"RELIANCE"`` — *not* ``"RELIANCE.NS"``).
        start, end : date
            Inclusive date range.
        interval : str
            Candle interval (see ``get_supported_intervals()``).
        exchange : str
            ``"NSE"`` or ``"BSE"`` — determines the yfinance suffix.
        instrument_type : str
            Currently only ``"equity"`` is supported.

        Returns
        -------
        FetchResult
        """
        # Map to yfinance interval string
        yf_interval = _INTERVAL_MAP.get(interval.lower().strip())
        if yf_interval is None:
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=False,
                error=f"Unsupported interval: {interval!r}. "
                      f"Supported: {list(_INTERVAL_MAP.keys())}",
            )

        # Convert symbol to yfinance format
        yf_symbol = self._mapper.to_yfinance(symbol, exchange)

        # Apply lookback and range restrictions
        start, end = self._apply_restrictions(yf_interval, start, end)

        if start > end:
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=True,
                error="",
                metadata={
                    "yf_symbol": yf_symbol,
                    "note": (
                        f"Date range falls outside yfinance's lookback "
                        f"limit for {yf_interval} data."
                    ),
                },
            )

        # Determine if we need to chunk the request
        limits = _YF_LIMITS.get(yf_interval, (0, 0))
        max_range = limits[1]

        if max_range > 0 and (end - start).days > max_range:
            # Chunk into multiple requests
            return self._fetch_chunked(
                yf_symbol=yf_symbol,
                symbol=symbol,
                start=start,
                end=end,
                yf_interval=yf_interval,
                max_range_days=max_range,
            )
        else:
            # Single request
            return self._fetch_single(
                yf_symbol=yf_symbol,
                symbol=symbol,
                start=start,
                end=end,
                yf_interval=yf_interval,
            )

    def fetch_instrument_list(self, exchange: str = "NSE") -> pd.DataFrame:
        """Not supported by yfinance — returns empty DataFrame."""
        logger.warning(
            "yfinance does not provide instrument lists. "
            "Use UniverseManager or Upstox instrument_manager instead."
        )
        return pd.DataFrame()

    # ── Restriction handling ──────────────────────────────────────────

    @staticmethod
    def _apply_restrictions(
        yf_interval: str,
        start: date,
        end: date,
    ) -> tuple[date, date]:
        """Clamp the date range to yfinance's per-interval limits.

        Returns the adjusted (start, end) tuple.
        """
        limits = _YF_LIMITS.get(yf_interval, (0, 0))
        max_lookback_days, _ = limits

        if max_lookback_days > 0:
            # Clamp start to the max lookback from today
            earliest_allowed = date.today() - timedelta(days=max_lookback_days)
            if start < earliest_allowed:
                logger.warning(
                    "yfinance %s data: lookback limited to %d days. "
                    "Clamping start from %s to %s.",
                    yf_interval, max_lookback_days, start, earliest_allowed,
                )
                start = earliest_allowed

        return start, end

    # ── Single request fetch ──────────────────────────────────────────

    def _fetch_single(
        self,
        yf_symbol: str,
        symbol: str,
        start: date,
        end: date,
        yf_interval: str,
    ) -> FetchResult:
        """Fetch data in a single yfinance API call."""
        logger.debug(
            "yfinance fetch: %s (%s) interval=%s %s → %s",
            symbol, yf_symbol, yf_interval, start, end,
        )

        try:
            # yfinance end date is exclusive, so add 1 day
            end_exclusive = end + timedelta(days=1)

            ticker = self._yf.Ticker(yf_symbol)
            df = ticker.history(
                start=start.isoformat(),
                end=end_exclusive.isoformat(),
                interval=yf_interval,
                auto_adjust=True,
                actions=False,
            )

            if df is None or df.empty:
                return FetchResult(
                    df=pd.DataFrame(),
                    symbol=symbol,
                    success=True,
                    metadata={"yf_symbol": yf_symbol},
                )

            df = self._standardise(df)

            logger.info(
                "Fetched %d rows for %s (%s → %s)",
                len(df), symbol, df.index.min(), df.index.max(),
            )

            return FetchResult(
                df=df, symbol=symbol, success=True,
                metadata={"yf_symbol": yf_symbol},
            )

        except Exception as exc:
            logger.error(
                "yfinance fetch failed for %s: %s (%s)",
                symbol, type(exc).__name__, exc,
            )
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=False,
                error=f"yfinance error: {exc}",
                metadata={"yf_symbol": yf_symbol},
            )

    # ── Chunked request fetch (for 1m data with 7-day limit) ─────────

    def _fetch_chunked(
        self,
        yf_symbol: str,
        symbol: str,
        start: date,
        end: date,
        yf_interval: str,
        max_range_days: int,
    ) -> FetchResult:
        """Fetch data by splitting the range into smaller chunks.

        Used for 1-minute data where yfinance limits each request
        to 7 calendar days.
        """
        chunks = self._generate_date_chunks(start, end, max_range_days)
        total = len(chunks)

        logger.info(
            "yfinance chunked fetch: %s (%s) %d chunks of ≤%d days "
            "(%s → %s)",
            symbol, yf_interval, total, max_range_days, start, end,
        )

        frames: list[pd.DataFrame] = []
        errors: list[str] = []

        for i, (c_start, c_end) in enumerate(chunks, 1):
            self._limiter.acquire()  # rate limit between chunks

            try:
                end_exclusive = c_end + timedelta(days=1)
                ticker = self._yf.Ticker(yf_symbol)
                df = ticker.history(
                    start=c_start.isoformat(),
                    end=end_exclusive.isoformat(),
                    interval=yf_interval,
                    auto_adjust=True,
                    actions=False,
                )

                if df is not None and not df.empty:
                    frames.append(self._standardise(df))
                    logger.debug(
                        "  Chunk %d/%d: %d rows (%s → %s)",
                        i, total, len(df), c_start, c_end,
                    )
                else:
                    logger.debug(
                        "  Chunk %d/%d: no data (%s → %s)",
                        i, total, c_start, c_end,
                    )

            except Exception as exc:
                msg = f"Chunk {i}/{total} ({c_start}→{c_end}): {exc}"
                logger.warning("  yfinance chunk error: %s", msg)
                errors.append(msg)

        if not frames:
            error_msg = "; ".join(errors) if errors else "No data"
            return FetchResult(
                df=pd.DataFrame(),
                symbol=symbol,
                success=len(errors) == 0,
                error=error_msg,
                metadata={"yf_symbol": yf_symbol},
            )

        combined = pd.concat(frames).sort_index()
        # Remove any overlapping duplicates at chunk boundaries
        combined = combined[~combined.index.duplicated(keep="last")]

        logger.info(
            "Fetched %d rows for %s across %d chunks (%s → %s)",
            len(combined), symbol, total,
            combined.index.min(), combined.index.max(),
        )

        return FetchResult(
            df=combined,
            symbol=symbol,
            success=True,
            error="; ".join(errors) if errors else "",
            metadata={"yf_symbol": yf_symbol, "chunks": total},
        )

    @staticmethod
    def _generate_date_chunks(
        start: date,
        end: date,
        max_days: int,
    ) -> list[tuple[date, date]]:
        """Split [start, end] into non-overlapping windows of max_days."""
        chunks: list[tuple[date, date]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=max_days - 1), end)
            chunks.append((cursor, chunk_end))
            cursor = chunk_end + timedelta(days=1)
        return chunks

    # ── Standardisation ───────────────────────────────────────────────

    @staticmethod
    def _standardise(df: pd.DataFrame) -> pd.DataFrame:
        """Convert yfinance output to canonical OHLCV schema.

        yfinance returns:
            Columns: Open, High, Low, Close, Volume
            Index: DatetimeIndex (may or may not be tz-aware)
        """
        # Rename columns to lowercase
        col_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        df = df.rename(columns=col_map)

        # Keep only OHLCV columns
        keep = [c for c in ("open", "high", "low", "close", "volume")
                if c in df.columns]
        df = df[keep].copy()

        # Add oi column (yfinance doesn't provide it)
        df["oi"] = 0

        # Ensure timezone-aware IST index
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        df.index.name = "timestamp"

        # Apply compact dtypes
        for col, dtype in OHLCV_DTYPES.items():
            if col in df.columns:
                try:
                    df[col] = df[col].astype(dtype)
                except (ValueError, TypeError):
                    pass  # Keep original dtype if cast fails

        return df.sort_index()


def _lazy_import_yfinance():
    """Import yfinance lazily to avoid import-time overhead."""
    try:
        import yfinance as yf
        return yf
    except ImportError:
        raise ImportError(
            "yfinance is required for YFinanceProvider. "
            "Install it with: pip install yfinance"
        ) from None
