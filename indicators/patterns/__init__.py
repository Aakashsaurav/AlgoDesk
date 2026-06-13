"""
indicators/patterns
-------------------
Pattern recognition layer for candlesticks, chart patterns, and Dow Theory.
"""
from .candlestick import scan_all_candlestick
from .chart_patterns import scan_all_chart
from .dow_patterns import find_swings, trend_structure

__all__ = [
    "scan_all_candlestick",
    "scan_all_chart",
    "find_swings",
    "trend_structure",
]
