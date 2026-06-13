"""
indicators/support_resistance
-----------------------------
Support and Resistance layer.
"""
from typing import List, Union, Optional
import pandas as pd

from .models import SRLevel, SRZone, sort_by_strength, filter_near_price
from .pivot import calculate_pivots, demark_pivots, to_sr_levels, weekly_pivots, monthly_pivots
from .price_based import calculate_swing_levels
from .fibonacci import fibonacci_retracements
from indicators.registry import register_indicator

@register_indicator(
    name="scan_all_levels",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low", "close"],
    outputs=["levels"],
    parameters={"methods": ["pivot", "swing", "fibonacci"]}
)
def scan_all_levels(df: pd.DataFrame, methods: List[str] = None) -> List[SRLevel]:
    """Scan and compile support/resistance levels from multiple methods."""
    if methods is None:
        methods = ["pivot", "swing", "fibonacci"]
        
    all_levels = []
    
    if "pivot" in methods and not df.empty:
        # Use previous bar for standard pivots if possible
        if len(df) >= 2:
            prev = df.iloc[-2]
            pivs = calculate_pivots(prev['high'], prev['low'], prev['close'])
            all_levels.extend(list(pivs.values()))
        else:
            last = df.iloc[-1]
            pivs = calculate_pivots(last['high'], last['low'], last['close'])
            all_levels.extend(list(pivs.values()))
            
    if "swing" in methods and not df.empty:
        swings = calculate_swing_levels(df['high'], df['low'])
        all_levels.extend(swings)
        
    if "fibonacci" in methods and not df.empty:
        highest = df['high'].max()
        lowest = df['low'].min()
        last_close = df['close'].iloc[-1]
        trend = "up" if last_close > (highest + lowest) / 2 else "down"
        fibs = fibonacci_retracements(highest, lowest, trend=trend)
        all_levels.extend(list(fibs.values()))
        
    return all_levels

def nearest_support(levels: List[Union[SRLevel, SRZone]], current_price: float) -> Optional[Union[SRLevel, SRZone]]:
    """Find the nearest support level below the current price."""
    supports = []
    for l in levels:
        if isinstance(l, SRLevel):
            if getattr(l, "type", "unknown") in ("support", "pivot", "unknown") and l.price < current_price:
                supports.append(l)
        elif isinstance(l, SRZone):
            if getattr(l, "type", "unknown") in ("support", "zone", "unknown") and l.upper_price < current_price:
                supports.append(l)
                
    if not supports:
        return None
        
    return max(supports, key=lambda x: x.price if isinstance(x, SRLevel) else x.upper_price)

def nearest_resistance(levels: List[Union[SRLevel, SRZone]], current_price: float) -> Optional[Union[SRLevel, SRZone]]:
    """Find the nearest resistance level above the current price."""
    resistances = []
    for l in levels:
        if isinstance(l, SRLevel):
            if getattr(l, "type", "unknown") in ("resistance", "pivot", "unknown") and l.price > current_price:
                resistances.append(l)
        elif isinstance(l, SRZone):
            if getattr(l, "type", "unknown") in ("resistance", "zone", "unknown") and l.lower_price > current_price:
                resistances.append(l)
                
    if not resistances:
        return None
        
    return min(resistances, key=lambda x: x.price if isinstance(x, SRLevel) else x.lower_price)

__all__ = [
    "SRLevel", 
    "SRZone",
    "sort_by_strength",
    "filter_near_price",
    "calculate_pivots", 
    "demark_pivots",
    "to_sr_levels",
    "weekly_pivots",
    "monthly_pivots",
    "calculate_swing_levels", 
    "fibonacci_retracements",
    "scan_all_levels",
    "nearest_support",
    "nearest_resistance"
]
