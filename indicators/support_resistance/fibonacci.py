"""
indicators/support_resistance/fibonacci.py
------------------------------------------
Fibonacci retracements and extensions.
"""
import pandas as pd
from typing import Dict, Tuple
from indicators.support_resistance.models import SRLevel
from indicators.registry import register_indicator

FIBO_RETRACEMENT_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIBO_EXTENSION_LEVELS = [1.272, 1.414, 1.618, 2.0, 2.618, 3.618, 4.236]

def _price_at_level(high: float, low: float, level: float, trend: str = "up") -> float:
    """Calculate the price at a specific Fibonacci level."""
    diff = high - low
    if trend == "up":
        return high - (diff * level)
    else:
        return low + (diff * level)

def _find_major_swing(high: pd.Series, low: pd.Series, window: int = 50) -> Tuple[float, float, str]:
    """Find the major swing high and low over a lookback window."""
    h = high.tail(window).max()
    l = low.tail(window).min()
    
    h_idx = high.tail(window).idxmax()
    l_idx = low.tail(window).idxmin()
    
    # If the high occurred after the low, it's an upward swing
    trend = "up" if h_idx > l_idx else "down"
    
    return h, l, trend

@register_indicator(
    name="fibonacci_retracements",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low"],
    outputs=["fib_0.0", "fib_0.236", "fib_0.382", "fib_0.5", "fib_0.618", "fib_0.786", "fib_1.0"],
    parameters={"trend": "up"}
)
def fibonacci_retracements(high: float, low: float, trend: str = "up") -> Dict[str, SRLevel]:
    """Calculate Fibonacci retracement levels for a given price range."""
    res = {}
    for level in FIBO_RETRACEMENT_LEVELS:
        price = _price_at_level(high, low, level, trend)
        level_type = "support" if trend == "up" else "resistance"
        res[f"fib_{level}"] = SRLevel(price=price, type=level_type, source="fibonacci")
        
    return res

@register_indicator(
    name="fibonacci_extensions",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low"],
    outputs=["levels"],
    parameters={"trend": "up"}
)
def fibonacci_extensions(high: float, low: float, trend: str = "up") -> Dict[str, SRLevel]:
    """Calculate Fibonacci extension levels for a given price range."""
    res = {}
    for level in FIBO_EXTENSION_LEVELS:
        price = _price_at_level(high, low, level, trend)
        level_type = "support" if trend == "up" else "resistance"
        res[f"fib_ext_{level}"] = SRLevel(price=price, type=level_type, source="fibonacci_extension")
        
    return res

@register_indicator(
    name="auto_fibonacci",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low"],
    outputs=["retracements", "extensions"],
    parameters={"window": 50}
)
def auto_fibonacci(high: pd.Series, low: pd.Series, window: int = 50) -> Dict[str, Dict[str, SRLevel]]:
    """Automatically find major swing and calculate retracements and extensions."""
    if len(high) < window or len(low) < window:
        return {"retracements": {}, "extensions": {}}
        
    h, l, trend = _find_major_swing(high, low, window)
    
    retracements = fibonacci_retracements(h, l, trend)
    extensions = fibonacci_extensions(h, l, trend)
    
    return {
        "retracements": retracements,
        "extensions": extensions
    }

__all__ = [
    "FIBO_RETRACEMENT_LEVELS",
    "FIBO_EXTENSION_LEVELS",
    "_price_at_level",
    "_find_major_swing",
    "fibonacci_retracements",
    "fibonacci_extensions",
    "auto_fibonacci"
]
