"""
screener/base.py
----------------
Core data classes, enums, and contracts for the unified screener module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


class ScreenMode(Enum):
    EOD = "EOD"
    HISTORICAL = "HISTORICAL"
    LIVE = "LIVE"


class SignalDirection(Enum):
    BULLISH = 1
    BEARISH = -1
    NEUTRAL = 0
    ANY = 2


class RankBy(Enum):
    SCORE = "SCORE"
    CLOSE = "CLOSE"
    VOLUME = "VOLUME"
    ATR_PCT = "ATR_PCT"
    RS_SCORE = "RS_SCORE"
    SIGNAL_STRENGTH = "SIGNAL_STRENGTH"


class ExportFormat(Enum):
    CSV = "CSV"
    JSON = "JSON"
    BOTH = "BOTH"
    NONE = "NONE"


@dataclass
class ScreenerConfig:
    # Identity
    scan_name: str = "scan"
    mode: ScreenMode = ScreenMode.EOD

    # Universe — accepts any symbol list
    symbols: list[str] = field(default_factory=list)

    # Parallelism
    n_workers: int = 8
    timeout_per_symbol: float = 30.0

    # Scoring
    use_weighted_scoring: bool = False
    rule_weights: dict[str, float] = field(default_factory=dict)

    # Pre-filters (applied before rules)
    min_bars: int = 50
    min_price: float = 0.0
    max_price: float = 0.0
    min_volume: float = 0.0
    min_atr_pct: float = 0.0

    # Output
    max_results: int = 0          # 0 = unlimited
    rank_by: RankBy = RankBy.SCORE
    rank_ascending: bool = False
    export_format: ExportFormat = ExportFormat.CSV
    export_dir: Path = Path("screener/output")

    # Historical mode
    date_range: tuple[str, str] | None = None    # (from_date, to_date)

    # Live mode
    tick_buffer_size: int = 1000   # max ticks per symbol in memory
    min_historical_bars: int = 200  # bars to pre-load before live scan

    def __post_init__(self):
        if self.n_workers <= 0:
            self.n_workers = 1
        if self.min_bars <= 0:
            self.min_bars = 1

    def validate(self) -> list[str]:
        errors = []
        if not self.symbols:
            errors.append("symbols list cannot be empty")
        if self.n_workers <= 0:
            errors.append("n_workers must be > 0")
        if self.min_bars <= 0:
            errors.append("min_bars must be > 0")
        if self.timeout_per_symbol <= 0:
            errors.append("timeout_per_symbol must be > 0")
        if self.mode == ScreenMode.HISTORICAL and not self.date_range:
            errors.append("date_range is required in HISTORICAL mode")
        return errors


@dataclass(slots=True)
class RuleResult:
    rule_name: str
    passed: bool
    value: float | None          # computed indicator value
    threshold: float | None      # the threshold compared against
    details: dict[str, Any]      # arbitrary metadata
    weight: float = 1.0          # for weighted scoring


@dataclass
class ScreenResult:
    symbol: str
    scan_date: str               # YYYY-MM-DD
    scan_time: str               # HH:MM:SS
    mode: ScreenMode

    # Rule results
    rules_passed: int
    rules_total: int
    passed: bool                  # rules_passed == rules_total

    # Scoring
    score: float                  # 0.0 to 1.0
    signal_direction: SignalDirection

    # Market snapshot at time of scan
    close: float
    volume: float
    atr_pct: float | None

    # Per-rule detail
    rule_details: dict[str, RuleResult]

    # Indicator values at signal bar
    indicator_values: dict[str, float]

    # Live mode extras
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    depth: dict | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "scan_date": self.scan_date,
            "scan_time": self.scan_time,
            "mode": self.mode.value,
            "rules_passed": self.rules_passed,
            "rules_total": self.rules_total,
            "passed": self.passed,
            "score": self.score,
            "signal_direction": self.signal_direction.name,
            "close": self.close,
            "volume": self.volume,
            "atr_pct": self.atr_pct,
            "rule_details": {
                k: {
                    "passed": v.passed,
                    "value": v.value,
                    "threshold": v.threshold,
                    "details": v.details,
                    "weight": v.weight
                } for k, v in self.rule_details.items()
            },
            "indicator_values": self.indicator_values,
            "ltp": self.ltp,
            "bid": self.bid,
            "ask": self.ask,
            "depth": self.depth
        }

    def to_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "scan_date": self.scan_date,
            "scan_time": self.scan_time,
            "mode": self.mode.value,
            "rules_passed": self.rules_passed,
            "rules_total": self.rules_total,
            "passed": self.passed,
            "score": self.score,
            "signal_direction": self.signal_direction.name,
            "close": self.close,
            "volume": self.volume,
            "atr_pct": self.atr_pct,
            "ltp": self.ltp,
            "bid": self.bid,
            "ask": self.ask
        }

    def passed_rules(self) -> list[str]:
        return [k for k, v in self.rule_details.items() if v.passed]

    def failed_rules(self) -> list[str]:
        return [k for k, v in self.rule_details.items() if not v.passed]


@dataclass
class ScanSummary:
    scan_name: str
    mode: ScreenMode
    scan_date: str
    elapsed_seconds: float
    symbols_scanned: int
    symbols_passed: int
    symbols_failed: int
    symbols_errored: int
    results: list[ScreenResult]

    def to_dict(self) -> dict:
        return {
            "scan_name": self.scan_name,
            "mode": self.mode.value,
            "scan_date": self.scan_date,
            "elapsed_seconds": self.elapsed_seconds,
            "symbols_scanned": self.symbols_scanned,
            "symbols_passed": self.symbols_passed,
            "symbols_failed": self.symbols_failed,
            "symbols_errored": self.symbols_errored,
            "results": [r.to_dict() for r in self.results]
        }

    def top_n(self, n: int) -> list[ScreenResult]:
        if n <= 0:
            return []
        return self.results[:n]

    def filter_by_direction(self, direction: SignalDirection) -> list[ScreenResult]:
        return [r for r in self.results if r.signal_direction == direction]


@dataclass(slots=True)
class TickData:
    symbol: str
    timestamp: pd.Timestamp
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    # Market depth (5 levels)
    bid_prices: list[float]
    bid_quantities: list[int]
    ask_prices: list[float]
    ask_quantities: list[int]
    # Derived
    bid_ask_spread: float
    total_bid_qty: int
    total_ask_qty: int

    def to_ohlcv_row(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume
        }

    def validate(self) -> bool:
        if self.ltp <= 0:
            return False
        if len(self.bid_prices) != 5:
            return False
        return True
