# Use cases:
# - Resolve built-in, third-party, and custom indicators from one standalone engine.
# - Keep strategy code similar to Backtrader while remaining broker-independent.
# - Provide a single indicator integration point for backtests and future live mode.
"""
indicators/engine.py
--------------------
Backtrader-style indicator engine.

This layer provides one place to resolve indicators from:
* the canonical modular pure-Python indicator modules
* the external-library bridge in ``indicators.bridge``
* user-registered custom indicator callables

Strategies can call this engine from ``self.I(...)`` during backtests so
indicator computation stays separate from trading logic.
"""

from __future__ import annotations

import logging
from importlib import import_module
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, List

import pandas as pd
from indicators.bridge import IndicatorBridge

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IndicatorSpec:
    """A single indicator request."""

    indicator: Any
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None
    library: str = "auto"


def _make_hashable(val: Any) -> Any:
    """Helper to convert unhashable objects recursively to hashable structures."""
    if isinstance(val, (pd.Series, pd.DataFrame)):
        return id(val)
    if isinstance(val, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in val.items()))
    if isinstance(val, (list, tuple, set)):
        return tuple(_make_hashable(item) for item in val)
    try:
        hash(val)
        return val
    except TypeError:
        return id(val)


class IndicatorEngine:
    """
    Resolve and compute indicators from built-ins, bridges, or custom callables.
    """

    def __init__(self, preferred_library: str = "auto", max_cache_size: int = 1000) -> None:
        self.preferred_library = preferred_library
        self._bridge = IndicatorBridge(preferred_library=preferred_library)
        self._custom: Dict[str, Callable[..., Any]] = {}
        self._cache: Dict[tuple, Any] = {}
        self._builtin_module_cache: Dict[str, Optional[Callable]] = {}
        self.max_cache_size = max_cache_size
        
        # Load user-defined custom indicators from SQLite
        try:
            from indicators.custom import CustomIndicatorLoader
            loader = CustomIndicatorLoader()
            loader.load_into_engine(self)
        except Exception as e:
            logger.error("Failed to load custom indicators from SQLite: %s", e)

    def clear_cache(self) -> None:
        """Clear the indicator memoization cache."""
        self._cache.clear()

    def register(self, name: str, func: Callable[..., Any]) -> None:
        """Register a custom indicator callable."""
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Indicator name must not be empty")
        if not callable(func):
            raise TypeError("Indicator function must be callable")
        self._custom[cleaned] = func
        self._bridge.register(cleaned, func)
        logger.info("Registered custom indicator: %s", cleaned)

    def has(self, name: str) -> bool:
        """Return True if the indicator is known to this engine."""
        return name in self._custom or self._has_builtin(name) or hasattr(self._bridge, name)

    def default_name(self, indicator: Any, fallback: str = "indicator") -> str:
        """Derive a reasonable display name for a computed indicator."""
        if isinstance(indicator, str):
            return indicator.strip()
        return getattr(indicator, "__name__", fallback) or fallback

    def resolve(
        self,
        indicator: Any,
        *args: Any,
        name: Optional[str] = None,
        library: str = "auto",
        **kwargs: Any,
    ) -> Any:
        """Alias for compute() to resolve and run an indicator."""
        return self.compute(indicator, *args, name=name, library=library, **kwargs)

    def compute(
        self,
        indicator: Any,
        *args: Any,
        name: Optional[str] = None,
        library: str = "auto",
        **kwargs: Any,
    ) -> Any:
        """
        Compute an indicator from a callable or a string name.

        If a string name is provided, the engine first checks custom
        registrations, then the canonical pure-Python library, and finally the
        bridge.  For bridge-backed indicators, the selected library is passed
        through to support ``pandas_ta`` / ``talib`` selection.
        """
        # Create a cache key using _make_hashable helper
        cache_key_args = tuple(_make_hashable(arg) for arg in args)
        cache_key_kwargs = tuple(sorted((k, _make_hashable(v)) for k, v in kwargs.items()))
        ind_key = indicator if isinstance(indicator, str) else id(indicator)
        cache_key = (ind_key, cache_key_args, cache_key_kwargs, library)

        if cache_key in self._cache:
            return self._cache[cache_key]

        fn = self._resolve(indicator, library=library)
        result = fn(*args, **kwargs)

        # LRU eviction
        if len(self._cache) >= self.max_cache_size:
            self._cache.pop(next(iter(self._cache)))

        self._cache[cache_key] = result
        return result

    def batch_compute(self, specs: List[IndicatorSpec]) -> Dict[str, Any]:
        """Compute multiple indicators efficiently, returning a dict of results."""
        results = {}
        for spec in specs:
            res = self.compute(
                spec.indicator,
                *spec.args,
                name=spec.name,
                library=spec.library,
                **spec.kwargs
            )
            # Use provided name or default derived name
            final_name = spec.name or self.default_name(spec.indicator)
            results[final_name] = res
        return results

    def spec(
        self,
        indicator: Any,
        *args: Any,
        name: Optional[str] = None,
        library: str = "auto",
        **kwargs: Any,
    ) -> IndicatorSpec:
        """Create a reusable indicator request object."""
        return IndicatorSpec(
            indicator=indicator,
            args=tuple(args),
            kwargs=dict(kwargs),
            name=name or self.default_name(indicator),
            library=library,
        )

    def get_registry_schema(self) -> List[Dict[str, Any]]:
        """Return the JSON schema for all registered indicators."""
        from indicators.registry import IndicatorRegistry
        return IndicatorRegistry.to_json_schema()

    def _resolve(self, indicator: Any, library: str = "auto") -> Callable[..., Any]:
        """Resolve an indicator into a callable."""
        if callable(indicator):
            return indicator

        if not isinstance(indicator, str):
            raise TypeError(
                f"indicator must be a callable or string, got {type(indicator).__name__}"
            )

        indicator_name = indicator.strip()
        if not indicator_name:
            raise ValueError("indicator name must not be empty")

        builtin = self._builtin_lookup(indicator_name)
        if indicator_name in self._custom:
            return self._custom[indicator_name]

        # By default, prefer canonical built-ins so their function signatures
        # remain the primary contract across strategies and backtests.
        if builtin is not None and library == "auto":
            return builtin

        # Bridge-backed indicators support explicit external library selection.
        if hasattr(self._bridge, indicator_name):
            bridge_method = getattr(self._bridge, indicator_name)

            def _call_bridge(*args: Any, **kwargs: Any) -> Any:
                try:
                    return bridge_method(*args, library=library, **kwargs)
                except TypeError:
                    return bridge_method(*args, **kwargs)

            return _call_bridge

        if builtin is not None:
            return builtin

        raise KeyError(
            f"Unknown indicator '{indicator_name}'. "
            f"Known custom indicators: {sorted(self._custom.keys())}"
        )

    def _has_builtin(self, name: str) -> bool:
        return self._builtin_lookup(name) is not None

    def _builtin_lookup(self, name: str) -> Optional[Callable[..., Any]]:
        """Look up canonical modular pure-Python indicator functions."""
        if name in self._builtin_module_cache:
            return self._builtin_module_cache[name]

        modules = []
        for module_name in (
            "indicators.moving_averages",
            "indicators.oscillators",
            "indicators.volatility",
            "indicators.trend",
            "indicators.statistics",
            "indicators.volume",
            "indicators.helpers",
            "indicators.patterns",
            "indicators.patterns.candlestick",
            "indicators.patterns.dow_patterns",
            "indicators.support_resistance",
        ):
            try:
                modules.append(import_module(module_name))
            except Exception:
                continue

        for module in modules:
            func = getattr(module, name, None)
            if callable(func):
                self._builtin_module_cache[name] = func
                return func
                
        self._builtin_module_cache[name] = None
        return None


__all__ = ["IndicatorEngine", "IndicatorSpec"]
