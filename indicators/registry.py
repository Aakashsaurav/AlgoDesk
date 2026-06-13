"""
indicators/registry.py
----------------------
Registry for indicator metadata (inputs, parameters, outputs).
Used by the Engine to know what an indicator needs and what it returns,
which is critical for the UI, Screener, and ExpressionParser.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Any, Optional

class Categories(str, Enum):
    TREND = "TREND"
    MOMENTUM = "MOMENTUM"
    VOLATILITY = "VOLATILITY"
    VOLUME = "VOLUME"
    PATTERN = "PATTERN"
    SUPPORT_RESISTANCE = "SUPPORT_RESISTANCE"
    STATISTICS = "STATISTICS"
    CUSTOM = "CUSTOM"

@dataclass
class IndicatorMeta:
    """Metadata describing an indicator's signature and outputs."""
    name: str
    category: str
    description: str
    inputs: List[str]  # e.g., ["close"], ["high", "low", "close"]
    parameters: Dict[str, Any]  # e.g., {"period": 14, "std_dev": 2.0}
    outputs: List[str]  # e.g., ["RSI_14"], ["macd", "signal", "histogram"]


class IndicatorRegistry:
    """Thread-safe registry for indicator metadata."""
    _registry: Dict[str, IndicatorMeta] = {}
    _lock = threading.RLock()

    @classmethod
    def register(cls, meta: IndicatorMeta) -> None:
        """Register indicator metadata."""
        with cls._lock:
            cls._registry[meta.name] = meta

    @classmethod
    def get(cls, name: str) -> Optional[IndicatorMeta]:
        """Get indicator metadata by name."""
        with cls._lock:
            return cls._registry.get(name)

    @classmethod
    def list_all(cls) -> Dict[str, IndicatorMeta]:
        """Return a copy of all registered indicators."""
        with cls._lock:
            return cls._registry.copy()

    @classmethod
    def auto_register_external(cls) -> None:
        """Auto-register TA-Lib and pandas-ta functions if available."""
        with cls._lock:
            try:
                import talib
                for func_name in talib.get_functions():
                    if func_name not in cls._registry:
                        cls.register(IndicatorMeta(
                            name=func_name,
                            category=Categories.CUSTOM.value,
                            description=f"TA-Lib {func_name}",
                            inputs=["*"],
                            parameters={},
                            outputs=[func_name]
                        ))
            except ImportError:
                pass

            try:
                import pandas_ta as ta
                # simple heuristics for pandas_ta functions
                for func_name in dir(ta):
                    if not func_name.startswith("_") and callable(getattr(ta, func_name)) and func_name.islower():
                        if func_name not in cls._registry:
                            cls.register(IndicatorMeta(
                                name=func_name,
                                category=Categories.CUSTOM.value,
                                description=f"pandas-ta {func_name}",
                                inputs=["*"],
                                parameters={},
                                outputs=[func_name]
                            ))
            except ImportError:
                pass

    @classmethod
    def get_by_category(cls, category: str) -> Dict[str, IndicatorMeta]:
        """Return indicators filtered by category."""
        with cls._lock:
            return {k: v for k, v in cls._registry.items() if v.category == category}

    @classmethod
    def search(cls, query: str) -> Dict[str, IndicatorMeta]:
        """Search indicators by name or description."""
        query = query.lower()
        with cls._lock:
            return {
                k: v for k, v in cls._registry.items()
                if query in v.name.lower() or query in v.description.lower()
            }

    @classmethod
    def to_json_schema(cls) -> List[Dict[str, Any]]:
        """Export registry as a list of dictionaries for the UI/Screener."""
        with cls._lock:
            return [
                {
                    "name": v.name,
                    "category": v.category,
                    "description": v.description,
                    "inputs": v.inputs,
                    "parameters": v.parameters,
                    "outputs": v.outputs,
                }
                for v in cls._registry.values()
            ]


def register_indicator(
    name: str,
    category: str,
    inputs: List[str],
    outputs: List[str],
    parameters: Optional[Dict[str, Any]] = None,
    description: str = "",
) -> Callable:
    """
    Decorator to register an indicator function with the registry.
    """
    def decorator(func: Callable) -> Callable:
        meta = IndicatorMeta(
            name=name,
            category=category,
            description=description or (func.__doc__ or "").strip().split("\n")[0],
            inputs=inputs,
            parameters=parameters or {},
            outputs=outputs,
        )
        IndicatorRegistry.register(meta)
        return func

    return decorator

__all__ = ["IndicatorMeta", "IndicatorRegistry", "register_indicator", "Categories"]

# Auto-register external libraries at module load
IndicatorRegistry.auto_register_external()
