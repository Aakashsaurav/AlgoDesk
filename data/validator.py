"""
data/validator.py
=================
OHLCV data-quality checks and auto-cleaning.

Designed to run on any DataFrame that follows the canonical OHLCV schema
(timestamp index, open/high/low/close/volume columns).

Usage
-----
    from data.validator import DataValidator

    v = DataValidator()
    result = v.validate(df, interval="daily")
    if not result.is_valid:
        for err in result.errors:
            print(f"ERROR: {err}")

    clean_df = v.clean(df)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["DataValidator", "ValidationResult"]

# ── Compact dtypes for cleaned output ────────────────────────────────────

_CLEAN_DTYPES: dict[str, str] = {
    "open":   "float32",
    "high":   "float32",
    "low":    "float32",
    "close":  "float32",
    "volume": "int32",
    "oi":     "int32",
}


@dataclass(slots=True)
class ValidationResult:
    """Container for validation outcomes.

    Attributes
    ----------
    is_valid : bool
        ``True`` if no errors were found (warnings are acceptable).
    errors : list[str]
        Critical issues that make the data unreliable.
    warnings : list[str]
        Non-critical issues worth investigating.
    stats : dict[str, Any]
        Summary statistics (row count, date range, etc.).
    """

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def merge(self, other: ValidationResult) -> ValidationResult:
        """Combine two results (logical AND on validity)."""
        return ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
            stats={**self.stats, **other.stats},
        )


class DataValidator:
    """OHLCV data quality validator.

    Each ``check_*`` method inspects one aspect of data quality and
    returns a :class:`ValidationResult`.  Call :meth:`validate` to run
    every check at once.
    """

    _REQUIRED_COLS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

    # ── Individual checks ─────────────────────────────────────────────

    def check_schema(self, df: pd.DataFrame) -> ValidationResult:
        """Verify required columns, DatetimeIndex, and timezone awareness."""
        result = ValidationResult()

        if df.empty:
            result.warnings.append("DataFrame is empty")
            return result

        # Check index type
        if not isinstance(df.index, pd.DatetimeIndex):
            result.is_valid = False
            result.errors.append(
                f"Index must be DatetimeIndex, got {type(df.index).__name__}"
            )
            return result  # further checks are meaningless

        # Timezone awareness
        if df.index.tz is None:
            result.warnings.append("Index is timezone-naive — expected IST")

        # Required columns
        missing = [c for c in self._REQUIRED_COLS if c not in df.columns]
        if missing:
            result.is_valid = False
            result.errors.append(f"Missing columns: {missing}")

        result.stats["rows"] = len(df)
        result.stats["columns"] = list(df.columns)
        if len(df) > 0:
            result.stats["date_range"] = (
                str(df.index.min()),
                str(df.index.max()),
            )

        return result

    def check_ohlcv_integrity(self, df: pd.DataFrame) -> ValidationResult:
        """Check OHLCV logical constraints.

        *  high >= max(open, close, low)
        *  low  <= min(open, close, high)
        *  close within [low, high]
        *  No negative prices
        *  No zero close prices
        """
        result = ValidationResult()
        if df.empty or not all(c in df.columns for c in ("open", "high", "low", "close")):
            return result

        o, h, l, c = df["open"], df["high"], df["low"], df["close"]

        # High must be >= all others
        bad_high = (h < o) | (h < c) | (h < l)
        n_bad_high = int(bad_high.sum())
        if n_bad_high > 0:
            result.warnings.append(f"{n_bad_high} bars where high < open/close/low")

        # Low must be <= all others
        bad_low = (l > o) | (l > c) | (l > h)
        n_bad_low = int(bad_low.sum())
        if n_bad_low > 0:
            result.warnings.append(f"{n_bad_low} bars where low > open/close/high")

        # Negative prices
        neg_mask = (o < 0) | (h < 0) | (l < 0) | (c < 0)
        n_neg = int(neg_mask.sum())
        if n_neg > 0:
            result.is_valid = False
            result.errors.append(f"{n_neg} bars with negative prices")

        # Zero close
        n_zero_close = int((c == 0).sum())
        if n_zero_close > 0:
            result.is_valid = False
            result.errors.append(f"{n_zero_close} bars with zero close price")

        result.stats["integrity_bad_high"] = n_bad_high
        result.stats["integrity_bad_low"] = n_bad_low
        result.stats["integrity_negative"] = n_neg
        result.stats["integrity_zero_close"] = n_zero_close

        return result

    def check_duplicates(self, df: pd.DataFrame) -> ValidationResult:
        """Detect duplicate timestamps."""
        result = ValidationResult()
        if df.empty:
            return result

        n_dup = int(df.index.duplicated().sum())
        if n_dup > 0:
            result.warnings.append(f"{n_dup} duplicate timestamps found")

        result.stats["duplicates"] = n_dup
        return result

    def check_gaps(
        self,
        df: pd.DataFrame,
        interval: str = "daily",
    ) -> ValidationResult:
        """Detect missing trading sessions.

        For ``"daily"``: checks for missing weekdays (Mon-Fri).
        For ``"minute"``: checks gaps within market hours (09:15-15:30).
        """
        result = ValidationResult()
        if df.empty or len(df) < 2:
            return result

        if interval == "daily":
            return self._check_daily_gaps(df, result)
        elif interval in ("minute", "1m", "1min"):
            return self._check_minute_gaps(df, result)

        # Unknown interval — skip gap analysis
        result.warnings.append(
            f"Gap check not implemented for interval={interval!r}"
        )
        return result

    def _check_daily_gaps(
        self,
        df: pd.DataFrame,
        result: ValidationResult,
    ) -> ValidationResult:
        """Check for missing business days (excludes weekends)."""
        dates = df.index.normalize().unique()
        bdays = pd.bdate_range(start=dates.min(), end=dates.max())
        missing = bdays.difference(dates)

        n_missing = len(missing)
        if n_missing > 0:
            # Some are likely holidays — only warn if >5% missing
            pct = n_missing / len(bdays) * 100
            msg = f"{n_missing} missing business days ({pct:.1f}% of range)"
            if pct > 10:
                result.warnings.append(msg + " — consider checking holidays")
            else:
                result.warnings.append(msg + " — likely holidays")

        result.stats["gap_missing_bdays"] = n_missing
        return result

    def _check_minute_gaps(
        self,
        df: pd.DataFrame,
        result: ValidationResult,
    ) -> ValidationResult:
        """Check for missing minutes within market hours (09:15–15:30)."""
        # Filter to market hours
        times = df.index.time
        import datetime as dt

        mkt_open = dt.time(9, 15)
        mkt_close = dt.time(15, 30)
        mask = (times >= mkt_open) & (times <= mkt_close)
        mkt_df = df.loc[mask]

        if len(mkt_df) < 2:
            return result

        # Check for gaps > 2 minutes (allowing for 1-min jitter)
        diffs = mkt_df.index.to_series().diff()
        large_gaps = diffs[diffs > pd.Timedelta(minutes=2)]
        n_gaps = len(large_gaps)

        if n_gaps > 0:
            result.warnings.append(
                f"{n_gaps} intra-day gaps > 2 minutes detected"
            )

        result.stats["gap_intraday_gaps"] = n_gaps
        return result

    def check_volume(self, df: pd.DataFrame) -> ValidationResult:
        """Detect zero-volume bars and volume spikes."""
        result = ValidationResult()
        if df.empty or "volume" not in df.columns:
            return result

        vol = df["volume"]

        # Zero-volume bars
        n_zero = int((vol == 0).sum())
        if n_zero > 0:
            pct = n_zero / len(df) * 100
            result.warnings.append(
                f"{n_zero} zero-volume bars ({pct:.1f}% of data)"
            )

        # Volume spikes (> 10× rolling median)
        if len(df) >= 20:
            median_vol = vol.rolling(20, min_periods=10).median()
            spikes = vol > (median_vol * 10)
            n_spikes = int(spikes.sum())
            if n_spikes > 0:
                result.warnings.append(
                    f"{n_spikes} volume spikes (>10× rolling median)"
                )
            result.stats["volume_spikes"] = n_spikes

        result.stats["volume_zero_bars"] = n_zero
        return result

    # ── Aggregate validation ──────────────────────────────────────────

    def validate(
        self,
        df: pd.DataFrame,
        interval: str = "daily",
    ) -> ValidationResult:
        """Run all validation checks and return a merged result.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data to validate.
        interval : str
            ``"daily"`` or ``"minute"`` — affects gap detection logic.

        Returns
        -------
        ValidationResult
        """
        result = self.check_schema(df)
        if not result.is_valid:
            # Schema is broken — further checks are unreliable
            return result

        result = result.merge(self.check_ohlcv_integrity(df))
        result = result.merge(self.check_duplicates(df))
        result = result.merge(self.check_gaps(df, interval=interval))
        result = result.merge(self.check_volume(df))

        status = "PASS" if result.is_valid else "FAIL"
        logger.info(
            "Validation %s — %d errors, %d warnings, %d rows",
            status,
            len(result.errors),
            len(result.warnings),
            result.stats.get("rows", 0),
        )
        return result

    # ── Auto-clean ────────────────────────────────────────────────────

    @staticmethod
    def clean(df: pd.DataFrame) -> pd.DataFrame:
        """Auto-fix common data issues.

        *  Remove duplicate timestamps (keep last).
        *  Sort by timestamp.
        *  Apply canonical dtypes (float32 prices, int32 volume/oi).
        *  Fill missing ``oi`` column with 0.

        Returns a **copy** — the input DataFrame is not modified.
        """
        if df.empty:
            return df.copy()

        cleaned = df.copy()

        # Remove duplicates
        cleaned = cleaned[~cleaned.index.duplicated(keep="last")]

        # Sort chronologically
        cleaned = cleaned.sort_index()

        # Ensure 'oi' exists
        if "oi" not in cleaned.columns:
            cleaned["oi"] = 0

        # Apply compact dtypes
        for col, dtype in _CLEAN_DTYPES.items():
            if col in cleaned.columns:
                try:
                    cleaned[col] = cleaned[col].astype(dtype)
                except (ValueError, TypeError):
                    logger.warning("Could not cast column %s to %s", col, dtype)

        return cleaned
