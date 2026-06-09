# Use cases:
# - Define broker-independent strategies usable in both backtest and live contexts.
# - Support both vectorized `generate_signals()` and event-driven `prepare()+on_bar()`.
# - Register indicators separately from execution logic for reporting and charting.
"""
strategies/base.py
===================
Unified strategy contract for AlgoDesk.

This module is the canonical phase-3 strategy layer.  It defines:
* the signal contract between strategy and engine
* the portfolio snapshot visible to strategies
* indicator registration through ``self.I(...)``
* vectorized and event-driven strategy execution patterns
* metadata and parameter helpers for registry/UI integration
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from indicators.engine import IndicatorEngine

logger = logging.getLogger(__name__)

MIN_WARMUP_BARS = 50
DEFAULT_SYMBOL = "__symbol__"

# P3 FIX: named constant so the on_bar bridge capital is visible and
# changeable in one place rather than a magic number in a private method.
_BRIDGE_CAPITAL: float = 500_000.0


class Action(str, Enum):
    """Signal action emitted by a strategy."""

    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"
    EXIT_ALL = "EXIT_ALL"


class OrderType(str, Enum):
    """Supported execution order types at strategy level."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(slots=True)
class Signal:
    """Trading instruction emitted by the strategy."""

    action: Action
    quantity: int = 0
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    tag: str = ""


@dataclass(slots=True)
class PortfolioState:
    """Read-only portfolio snapshot passed to event-driven strategies."""

    cash: float
    total_value: float
    open_positions: Dict[str, int] = field(default_factory=dict)
    open_position_pnl: Dict[str, float] = field(default_factory=dict)
    peak_value: float = 0.0
    current_drawdown: float = 0.0

    def is_long(self, symbol: str = DEFAULT_SYMBOL) -> bool:
        return self.open_positions.get(symbol, 0) > 0

    def is_short(self, symbol: str = DEFAULT_SYMBOL) -> bool:
        return self.open_positions.get(symbol, 0) < 0

    def is_flat(self, symbol: str = DEFAULT_SYMBOL) -> bool:
        return self.open_positions.get(symbol, 0) == 0

    def position_size(self, symbol: str = DEFAULT_SYMBOL) -> int:
        return self.open_positions.get(symbol, 0)


@dataclass(slots=True)
class StrategyMetadata:
    """Serializable metadata used by registry, UI, and tests."""

    class_name: str
    display_name: str
    description: str
    category: str
    params: Dict[str, Any]
    module_path: str


@dataclass(slots=True)
class _RegisteredIndicator:
    """Container for indicators registered through `self.I()`."""

    name: str
    series: pd.Series


class BaseStrategy(ABC):
    """
    Base class for every AlgoDesk strategy.

    A strategy can work in either mode:
    1. Vectorized: override `generate_signals(df)`
    2. Event-driven: override `prepare(df)` and `on_bar(...)`
    """

    PARAM_SCHEMA: List[Dict[str, Any]] = []
    DESCRIPTION: str = ""
    CATEGORY: str = "Custom"
    SYMBOL_SCOPE: str = "single"

    def __init__(
        self,
        name: str = "Unnamed Strategy",
        description: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.description = description or self.DESCRIPTION
        self.params: Dict[str, Any] = dict(params or {})
        self.logger = logging.getLogger(f"strategy.{self.__class__.__name__}")
        self._indicators: List[_RegisteredIndicator] = []
        self._indicator_engine = IndicatorEngine()
        self.validate_params()

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute indicators before event-driven bar iteration."""
        return df

    def on_bar(
        self,
        index: int,
        row: pd.Series,
        portfolio: PortfolioState,
    ) -> List[Signal]:
        """Return zero or more signals for the current bar."""
        return []

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Default implementation for event-driven strategies.

        Subclasses can override for vectorized execution. If not overridden,
        the base class bridges `prepare()+on_bar()` into a `signal` column.
        """
        return self._generate_signals_from_on_bar(df)

    def validate_params(self) -> None:
        """Validate the current parameter set. Override for strategy-specific rules."""
        if not isinstance(self.params, dict):
            raise TypeError("Strategy params must be a dictionary.")

    def on_entry_stop(
        self,
        bar_idx: int,
        row: pd.Series,
        direction: int,
    ) -> Optional[float]:
        """Optional custom stop-loss hook."""
        return None

    def on_bar_close(
        self,
        bar_idx: int,
        row: pd.Series,
        direction: int,
        current_sl: float,
    ) -> float:
        """Optional trailing-stop hook."""
        return current_sl

    def on_size(
        self,
        cash: float,
        price: float,
        bar_idx: int,
        row: pd.Series,
    ) -> Optional[int]:
        """Optional custom position sizing hook."""
        return None

    def I(
        self,
        fn: Callable | str,
        *args: Any,
        name: Optional[str] = None,
        library: str = "auto",
        **kwargs: Any,
    ) -> Any:
        """Compute an indicator and register it for charting/reporting."""
        indicator_name = name or self._indicator_engine.default_name(
            fn,
            fallback=f"ind_{len(self._indicators)}",
        )
        result = self._indicator_engine.compute(
            fn,
            *args,
            name=indicator_name,
            library=library,
            **kwargs,
        )

        if isinstance(result, pd.Series):
            self._indicators.append(_RegisteredIndicator(indicator_name, result))
        elif isinstance(result, pd.DataFrame):
            for column in result.columns:
                self._indicators.append(
                    _RegisteredIndicator(f"{indicator_name}_{column}", result[column])
                )

        return result

    @property
    def registered_indicators(self) -> List[_RegisteredIndicator]:
        return list(self._indicators)

    def clear_indicators(self) -> None:
        self._indicators.clear()

    def get_params(self) -> Dict[str, Any]:
        return dict(self.params)

    def get_parameters(self) -> Dict[str, Any]:
        return self.get_params()

    def set_params(self, **kwargs: Any) -> None:
        self.params.update(kwargs)
        self.validate_params()

    def get_metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            class_name=self.__class__.__name__,
            display_name=self.name,
            description=self.description,
            category=self.CATEGORY,
            params=self.get_params(),
            module_path=self.__class__.__module__,
        )

    def clone(self, **overrides: Any) -> "BaseStrategy":
        new_params = self.get_params()
        new_params.update(overrides)
        return self.__class__(**new_params)

    def uses_vectorized_mode(self) -> bool:
        return self.__class__.generate_signals is not BaseStrategy.generate_signals

    def _validate_and_prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate input market data and initialize strategy output columns.
        """
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Strategy input must be a pandas DataFrame.")

        required = ["open", "high", "low", "close", "volume"]
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ValueError(
                f"Strategy '{self.name}' missing required columns: {missing}. "
                f"Available columns: {list(df.columns)}"
            )
        if df.empty:
            raise ValueError(f"Strategy '{self.name}' received an empty DataFrame.")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError(
                f"Strategy '{self.name}' requires a DatetimeIndex, got "
                f"{type(df.index).__name__}."
            )
        if df.index.has_duplicates:
            raise ValueError(f"Strategy '{self.name}' received duplicate timestamps.")

        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        else:
            df = df.copy()

        if len(df) < MIN_WARMUP_BARS:
            self.logger.warning(
                "Only %s bars supplied; warm-up-sensitive strategies may be unreliable.",
                len(df),
            )

        self.clear_indicators()
        if "signal" not in df.columns:
            df["signal"] = 0
        else:
            df["signal"] = df["signal"].fillna(0).astype(int)
        if "signal_tag" not in df.columns:
            df["signal_tag"] = ""
        else:
            df["signal_tag"] = df["signal_tag"].fillna("").astype(str)
        return df

    def _suppress_warmup_signals(self, df: pd.DataFrame, warmup_bars: int) -> pd.DataFrame:
        """Force signals to zero during the warm-up region."""
        if warmup_bars > 0:
            limit = min(len(df), warmup_bars)
            df.iloc[:limit, df.columns.get_loc("signal")] = 0
            if "signal_tag" in df.columns:
                df.iloc[:limit, df.columns.get_loc("signal_tag")] = ""
        return df

    def _generate_signals_from_on_bar(self, df: pd.DataFrame) -> pd.DataFrame:
        """Bridge event-driven `on_bar()` strategies into tabular signals."""
        df = self._validate_and_prepare(df)
        df = self.prepare(df)

        cash = _BRIDGE_CAPITAL  # P3 FIX: was hardcoded 500_000.0
        peak = cash
        current_position = 0

        for idx in range(len(df)):
            row = df.iloc[idx]
            portfolio = PortfolioState(
                cash=cash,
                total_value=cash,
                open_positions={DEFAULT_SYMBOL: current_position} if current_position else {},
                peak_value=peak,
            )
            signals = self.on_bar(idx, row, portfolio)
            if not signals:
                continue

            last = signals[-1]
            if last.action in (Action.BUY, Action.COVER):
                df.iloc[idx, df.columns.get_loc("signal")] = 1
                current_position = 1
            elif last.action in (Action.SELL, Action.SHORT, Action.EXIT_ALL):
                df.iloc[idx, df.columns.get_loc("signal")] = -1
                current_position = -1 if last.action == Action.SHORT else 0

            if last.tag and "signal_tag" in df.columns:
                df.iloc[idx, df.columns.get_loc("signal_tag")] = last.tag

        return df

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name!r}, "
            f"params={self.params!r}, category={self.CATEGORY!r})"
        )


__all__ = [
    "Action",
    "BaseStrategy",
    "DEFAULT_SYMBOL",
    "MIN_WARMUP_BARS",
    "OrderType",
    "PortfolioState",
    "Signal",
    "StrategyMetadata",
]