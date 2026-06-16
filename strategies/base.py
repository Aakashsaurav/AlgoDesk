from __future__ import annotations

import logging
import threading
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from indicators.engine import IndicatorEngine
from strategies.categories import StrategyCategory
from strategies.contracts import (
    DEFAULT_SYMBOL,
    Action,
    OrderType,
    ParamSpec,
    PortfolioState,
    Signal,
    StrategyMetadata,
    StrategyMode,
    StrategyScope,
)

logger = logging.getLogger(__name__)

MIN_WARMUP_BARS = 50

# P3 FIX: named constant so the on_bar bridge capital is visible and
# changeable in one place rather than a magic number in a private method.
_BRIDGE_CAPITAL: float = 500_000.0

_SHARED_ENGINE: IndicatorEngine | None = None
_ENGINE_LOCK = threading.Lock()

def _get_shared_engine() -> IndicatorEngine:
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        with _ENGINE_LOCK:
            if _SHARED_ENGINE is None:
                _SHARED_ENGINE = IndicatorEngine()
    return _SHARED_ENGINE

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
    CATEGORY: str = StrategyCategory.CUSTOM.value
    SYMBOL_SCOPE: StrategyScope = StrategyScope.SINGLE_SYMBOL
    MODE: StrategyMode = StrategyMode.VECTORIZED
    REQUIRED_EXTRA_COLUMNS: Tuple[str, ...] = ()
    ALLOW_SHORT: bool = True
    ALLOW_REVERSAL: bool = False

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
        self._indicator_engine = _get_shared_engine()
        self.validate_params()

    @classmethod
    def clear_indicator_cache(cls) -> None:
        global _SHARED_ENGINE
        with _ENGINE_LOCK:
            _SHARED_ENGINE = None

    @property
    def warmup_period(self) -> int:
        return MIN_WARMUP_BARS

    @property
    def required_columns(self) -> Tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def required_input_columns(self) -> Tuple[str, ...]:
        return self.required_columns + self.REQUIRED_EXTRA_COLUMNS

    def validate_params(self) -> None:
        """Validate the current parameter set. Override for strategy-specific rules."""
        if not isinstance(self.params, dict):
            raise TypeError("Strategy params must be a dictionary.")

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

    def on_portfolio(
        self,
        timestamp: pd.Timestamp,
        bars: Dict[str, pd.Series],
        portfolio: PortfolioState,
    ) -> List[Signal]:
        """Return signals based on portfolio-level state across multiple symbols."""
        return []

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Default implementation for event-driven strategies.

        Subclasses can override for vectorized execution. If not overridden,
        the base class bridges `prepare()+on_bar()` into a `signal` column.
        """
        return self._generate_signals_from_on_bar(df)

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
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        tag: str,
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
        # Force a dict to only pass serializable simple params if possible.
        new_params = self.get_params()
        new_params.update(overrides)
        return self.__class__(**new_params)

    def uses_vectorized_mode(self) -> bool:
        return self.__class__.generate_signals is not BaseStrategy.generate_signals

    def _validate_and_prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"Strategy {self.__class__.__name__} input must be a pandas DataFrame.")

        required = self.required_input_columns()
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(
                f"Strategy '{self.__class__.__name__}' missing required columns: {missing}. "
                f"Available columns: {list(df.columns)}"
            )
        if df.empty:
            raise ValueError(f"Strategy '{self.__class__.__name__}' received an empty DataFrame.")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError(
                f"Strategy '{self.__class__.__name__}' requires a DatetimeIndex, got "
                f"{type(df.index).__name__}."
            )
        if df.index.has_duplicates:
            raise ValueError(f"Strategy '{self.__class__.__name__}' received duplicate timestamps.")

        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        else:
            df = df.copy()

        if len(df) < self.warmup_period:
            self.logger.warning(
                "Only %s bars supplied; warm-up period is %s bars.",
                len(df),
                self.warmup_period
            )

        self.clear_indicators()
        return self._ensure_output_columns(df)

    def _ensure_output_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = {
            "signal": 0,
            "signal_tag": "",
            "stop_loss": np.nan,
            "take_profit": np.nan,
            "confidence": np.nan,
            "reason": "",
            "order_spec": None,
        }
        for col, default_val in cols.items():
            if col not in df.columns:
                df[col] = default_val

        return df

    def _normalize_signal_values(self, df: pd.DataFrame) -> pd.DataFrame:
        df["signal"] = df["signal"].fillna(0).astype(int)
        df["signal_tag"] = df["signal_tag"].fillna("").astype(str)
        return df

    def _finalize_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._ensure_output_columns(df)
        df = self._normalize_signal_values(df)
        df = self._suppress_warmup_signals(df, self.warmup_period)
        return df

    def _suppress_warmup_signals(self, df: pd.DataFrame, warmup_bars: int) -> pd.DataFrame:
        if warmup_bars > 0:
            limit_idx = df.index[:min(len(df), warmup_bars)]
            df.loc[limit_idx, "signal"] = 0
            df.loc[limit_idx, "signal_tag"] = ""
        return df

    def _generate_signals_from_on_bar(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._validate_and_prepare(df)
        df = self.prepare(df)

        cash = _BRIDGE_CAPITAL
        peak = cash
        current_position = 0

        signal_arr = df["signal"].values.copy()
        tag_arr = df["signal_tag"].values.copy()

        os_loc = df.columns.get_loc("order_spec")
        sl_loc = df.columns.get_loc("stop_loss")
        tp_loc = df.columns.get_loc("take_profit")
        conf_loc = df.columns.get_loc("confidence")
        rs_loc = df.columns.get_loc("reason")
        
        for i in range(len(df)):
            row = df.iloc[i]
            portfolio = PortfolioState(
                cash=cash,
                total_value=cash,
                open_positions={DEFAULT_SYMBOL: current_position} if current_position else {},
                peak_value=peak,
            )
            signals = self.on_bar(i, row, portfolio)
            if not signals:
                continue

            last = signals[-1]
            if last.action in (Action.BUY, Action.COVER):
                signal_arr[i] = 1
                current_position = 1
            elif last.action in (Action.SELL, Action.SHORT, Action.EXIT_ALL):
                signal_arr[i] = -1
                current_position = -1 if last.action == Action.SHORT else 0

            if last.tag:
                tag_arr[i] = last.tag

            if getattr(last, "order_spec", None) is not None:
                df.iat[i, os_loc] = last.order_spec
            if last.stop_loss is not None:
                df.iat[i, sl_loc] = last.stop_loss
            if last.take_profit is not None:
                df.iat[i, tp_loc] = last.take_profit
            if getattr(last, "confidence", None) is not None:
                df.iat[i, conf_loc] = last.confidence
            if getattr(last, "reason", None) is not None:
                df.iat[i, rs_loc] = last.reason

        df["signal"] = signal_arr
        df["signal_tag"] = tag_arr

        return self._finalize_signals(df)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize strategy to dict."""
        return {
            "class_name": self.__class__.__name__,
            "module_path": self.__class__.__module__,
            "name": self.name,
            "params": self.get_params(),
            "category": self.CATEGORY,
            "required_columns": list(self.required_input_columns()),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseStrategy":
        """Deserialize from dict using registry."""
        from strategies.registry import load_strategy
        return load_strategy(data["class_name"], data.get("params", {}))

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
    "ParamSpec",
    "StrategyMode",
    "StrategyScope",
]