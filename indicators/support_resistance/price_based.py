"""
indicators/support_resistance/price_based.py
--------------------------------------------
Price-based support/resistance using historical swings and clusters.
"""
import math
import numpy as np
import pandas as pd
from typing import List

from indicators.support_resistance.models import SRLevel, SRZone
from indicators.patterns.dow_patterns import find_swings
from indicators.registry import register_indicator

def _cluster_levels(levels: List[float], tolerance: float = 0.005) -> List[float]:
    """Cluster similar price levels."""
    if not levels:
        return []
    
    levels = sorted(levels)
    clusters = []
    current_cluster = [levels[0]]
    
    for level in levels[1:]:
        if level <= current_cluster[0] * (1 + tolerance):
            current_cluster.append(level)
        else:
            clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [level]
            
    if current_cluster:
        clusters.append(sum(current_cluster) / len(current_cluster))
        
    return clusters

def _score_level(price: float, closes: pd.Series, tolerance: float = 0.005) -> float:
    """Score a price level based on historical interactions (touches)."""
    if closes.empty:
        return 0.0
    upper = price * (1 + tolerance)
    lower = price * (1 - tolerance)
    touches = ((closes >= lower) & (closes <= upper)).sum()
    # Normalize score between 0 and 1, assuming e.g. 10 touches is "max" strength
    return min(touches / 10.0, 1.0)

@register_indicator(
    name="calculate_swing_levels",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low", "close"],
    outputs=["levels"],
    parameters={"window": 5}
)
def calculate_swing_levels(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> List[SRLevel]:
    """Find key support/resistance levels from recent swing highs/lows."""
    swings = find_swings(high, low, window)
    levels = []
    
    # Extract unique swing highs and lows
    swing_highs = swings['swing_high_price'].dropna().unique()
    swing_lows = swings['swing_low_price'].dropna().unique()
    
    for price in swing_highs:
        strength = _score_level(price, close)
        levels.append(SRLevel(price=price, level_type="resistance", source="swing", strength=strength))
        
    for price in swing_lows:
        strength = _score_level(price, close)
        levels.append(SRLevel(price=price, level_type="support", source="swing", strength=strength))
        
    return levels

@register_indicator(
    name="volume_profile_sr",
    category="SUPPORT_RESISTANCE",
    inputs=["close", "volume"],
    outputs=["levels"],
    parameters={"bins": 50, "prominence": 1.5}
)
def volume_profile_sr(close: pd.Series, volume: pd.Series, bins: int = 50, prominence: float = 1.5) -> List[SRLevel]:
    """Find Support/Resistance levels using High Volume Nodes (HVNs) in Volume Profile."""
    if close.empty or volume.empty:
        return []
    
    min_price = close.min()
    max_price = close.max()
    
    if min_price == max_price:
        return []
        
    bin_edges = np.linspace(min_price, max_price, bins + 1)
    
    # Use pandas cut to group volumes
    volume_by_price = volume.groupby(pd.cut(close, bins=bin_edges, include_lowest=True), observed=False).sum()
    
    # Find peaks (HVNs)
    mean_volume = volume_by_price.mean()
    threshold = mean_volume * prominence
    
    hvns = volume_by_price[volume_by_price > threshold]
    
    levels = []
    for interval, vol in hvns.items():
        if pd.notna(interval):
            price = interval.mid
            levels.append(SRLevel(price=price, level_type="unknown", source="volume_profile"))
            
    return levels

@register_indicator(
    name="round_number_sr",
    category="SUPPORT_RESISTANCE",
    inputs=["close"],
    outputs=["levels"],
    parameters={"levels_count": 5}
)
def round_number_sr(close: pd.Series, levels_count: int = 5) -> List[SRLevel]:
    """Identify psychological support and resistance at round numbers."""
    if close.empty:
        return []
    
    current_price = close.iloc[-1]
    
    if current_price == 0:
        return []
        
    oom = 10 ** math.floor(math.log10(current_price))
    
    if current_price / oom < 5:
        step = oom / 10
    else:
        step = oom / 2
        
    if step == 0:
        return []
        
    closest_round = round(current_price / step) * step
    
    levels = []
    for i in range(-levels_count, levels_count + 1):
        price = closest_round + (i * step)
        if price <= 0:
            continue
        level_type = "resistance" if price > current_price else ("support" if price < current_price else "current")
        levels.append(SRLevel(price=price, level_type=level_type, source="round_number"))
        
    return levels

@register_indicator(
    name="recent_high_low",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low", "close"],
    outputs=["levels"],
    parameters={"window": 20}
)
def recent_high_low(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> List[SRLevel]:
    """Calculate support and resistance from recent N-period highs and lows."""
    if len(high) < window or len(low) < window:
        return []
        
    recent_high = high.tail(window).max()
    recent_low = low.tail(window).min()
    current_price = close.iloc[-1]
    
    levels = []
    if pd.notna(recent_high):
        levels.append(SRLevel(price=recent_high, level_type="resistance", source="recent_high"))
    if pd.notna(recent_low):
        levels.append(SRLevel(price=recent_low, level_type="support", source="recent_low"))
        
    return levels

__all__ = [
    "calculate_swing_levels",
    "_cluster_levels",
    "_score_level",
    "volume_profile_sr",
    "round_number_sr",
    "recent_high_low"
]
