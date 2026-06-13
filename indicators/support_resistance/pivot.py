"""
indicators/support_resistance/pivot.py
--------------------------------------
Pivot Point calculations.
"""
from typing import Dict, List
import pandas as pd
from indicators.support_resistance.models import SRLevel
from indicators.registry import register_indicator

@register_indicator(
    name="calculate_pivots",
    category="SUPPORT_RESISTANCE",
    inputs=["high", "low", "close"],
    outputs=["P", "R1", "S1", "R2", "S2", "R3", "S3", "R4", "S4"],
    parameters={"method": "classic"}
)

def calculate_pivots(high: float, low: float, close: float, method: str = "classic") -> Dict[str, SRLevel]:
    """
    Calculate pivot points based on previous period OHLC.
    Methods: classic, camarilla, woodie, demark.
    """
    pivots = {}
    
    if method == "classic":
        p = (high + low + close) / 3
        pivots["P"] = SRLevel(price=p, type="pivot", source="classic")
        pivots["R1"] = SRLevel(price=(2 * p) - low, type="resistance", source="classic")
        pivots["S1"] = SRLevel(price=(2 * p) - high, type="support", source="classic")
        pivots["R2"] = SRLevel(price=p + (high - low), type="resistance", source="classic")
        pivots["S2"] = SRLevel(price=p - (high - low), type="support", source="classic")
        
    elif method == "woodie":
        p = (high + low + 2 * close) / 4
        pivots["P"] = SRLevel(price=p, type="pivot", source="woodie")
        pivots["R1"] = SRLevel(price=(2 * p) - low, type="resistance", source="woodie")
        pivots["S1"] = SRLevel(price=(2 * p) - high, type="support", source="woodie")
        pivots["R2"] = SRLevel(price=p + high - low, type="resistance", source="woodie")
        pivots["S2"] = SRLevel(price=p - high + low, type="support", source="woodie")
        
    elif method == "camarilla":
        range_hl = high - low
        pivots["R4"] = SRLevel(price=close + (range_hl * 1.1) / 2, type="resistance", source="camarilla")
        pivots["R3"] = SRLevel(price=close + (range_hl * 1.1) / 4, type="resistance", source="camarilla")
        pivots["S3"] = SRLevel(price=close - (range_hl * 1.1) / 4, type="support", source="camarilla")
        pivots["S4"] = SRLevel(price=close - (range_hl * 1.1) / 2, type="support", source="camarilla")

    elif method == "fibonacci":
        p = (high + low + close) / 3
        range_hl = high - low
        pivots["P"] = SRLevel(price=p, type="pivot", source="fibonacci")
        pivots["R1"] = SRLevel(price=p + 0.382 * range_hl, type="resistance", source="fibonacci")
        pivots["R2"] = SRLevel(price=p + 0.618 * range_hl, type="resistance", source="fibonacci")
        pivots["R3"] = SRLevel(price=p + 1.000 * range_hl, type="resistance", source="fibonacci")
        pivots["S1"] = SRLevel(price=p - 0.382 * range_hl, type="support", source="fibonacci")
        pivots["S2"] = SRLevel(price=p - 0.618 * range_hl, type="support", source="fibonacci")
        pivots["S3"] = SRLevel(price=p - 1.000 * range_hl, type="support", source="fibonacci")

    return pivots

def demark_pivots(open_price: float, high: float, low: float, close: float) -> Dict[str, SRLevel]:
    """Calculate DeMark pivot points."""
    if close < open_price:
        x = high + (2 * low) + close
    elif close > open_price:
        x = (2 * high) + low + close
    else:
        x = high + low + (2 * close)
        
    p = x / 4
    r1 = x / 2 - low
    s1 = x / 2 - high
    
    return {
        "P": SRLevel(price=p, type="pivot", source="demark"),
        "R1": SRLevel(price=r1, type="resistance", source="demark"),
        "S1": SRLevel(price=s1, type="support", source="demark")
    }

def to_sr_levels(pivots_dict: Dict[str, SRLevel]) -> List[SRLevel]:
    """Convert pivot dictionary to a list of SRLevel objects."""
    return list(pivots_dict.values())

def weekly_pivots(df: pd.DataFrame, method: str = "classic") -> Dict[str, SRLevel]:
    """Calculate weekly pivot points using resampled OHLC."""
    if df.empty or len(df) < 2:
        return {}
    
    # Capital 'W' for weekly resample
    weekly = df.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    if len(weekly) < 2:
        return {}
    
    # Previous completed week
    prev = weekly.iloc[-2]
    if method == "demark":
        return demark_pivots(prev['open'], prev['high'], prev['low'], prev['close'])
    return calculate_pivots(prev['high'], prev['low'], prev['close'], method=method)

def monthly_pivots(df: pd.DataFrame, method: str = "classic") -> Dict[str, SRLevel]:
    """Calculate monthly pivot points using resampled OHLC."""
    if df.empty or len(df) < 2:
        return {}
        
    # 'ME' for month end or 'M' for backwards compatibility
    monthly = df.resample('M').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    if len(monthly) < 2:
        return {}
    
    # Previous completed month
    prev = monthly.iloc[-2]
    if method == "demark":
        return demark_pivots(prev['open'], prev['high'], prev['low'], prev['close'])
    return calculate_pivots(prev['high'], prev['low'], prev['close'], method=method)

__all__ = ["calculate_pivots", "demark_pivots", "to_sr_levels", "weekly_pivots", "monthly_pivots"]
