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
from typing import Any, Callable, Dict, Optional

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


class IndicatorEngine:
    """
    Resolve and compute indicators from built-ins, bridges, or custom callables.
    """

    def __init__(self, preferred_library: str = "auto") -> None:
        self.preferred_library = preferred_library
        self._bridge = IndicatorBridge(preferred_library=preferred_library)
        self._custom: Dict[str, Callable[..., Any]] = {}

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
        fn = self._resolve(indicator, library=library)
        return fn(*args, **kwargs)

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
        modules = []
        for module_name in (
            "indicators.moving_averages",
            "indicators.oscillators",
            "indicators.volatility",
            "indicators.trend",
            "indicators.statistics",
            "indicators.volume",
            "indicators.helpers",
        ):
            try:
                modules.append(import_module(module_name))
            except Exception:
                continue

        for module in modules:
            func = getattr(module, name, None)
            if callable(func):
                return func
        return None


__all__ = ["IndicatorEngine", "IndicatorSpec"]
