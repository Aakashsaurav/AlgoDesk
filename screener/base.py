# Use cases:
# - Define configurable screening sessions over multiple tickers.
# - Share coherent result metadata so the UI or CLI can report passes.
# - Provide reusable abstract base rules that leverage the indicator stack.
"""
screener/base.py
----------------
Core data classes for the standalone screener module.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pandas import DataFrame

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScreenerConfig:
    """
    Configuration for one screening session.

    Attributes
    ----------
    tickers : List[str]
        Symbols to test.
    instrument_type : str
    exchange : str
    unit : str
    interval : int
    from_date : Optional[str]
    to_date : Optional[str]
    period : Optional[str]
    """
    tickers: List[str]
    instrument_type: str = "EQUITY"
    exchange: str = "NSE"
    unit: str = "days"
    interval: int = 1
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    period: Optional[str] = None
    filter_hours: bool = False


@dataclass(slots=True)
class ScreenResult:
    ticker: str
    passed: bool
    rule_name: str
    timestamp: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class ScreenRule(ABC):
    """Abstract rule that inspects OHLCV to decide a pass/fail."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate(self, df: DataFrame) -> Optional[Dict[str, Any]]:
        """
        Run the rule on an OHLCV DataFrame.

        Returns
        -------
        dict or None
            Metadata when the rule passes, or None when it fails.
        """
        ...
