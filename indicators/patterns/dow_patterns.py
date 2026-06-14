"""
indicators/patterns/dow_patterns.py
-----------------------------------
Dow Theory patterns (higher highs, lower lows).
"""
import numpy as np
import pandas as pd
from indicators.registry import register_indicator

def swing_highs(series: pd.Series, order: int = 5) -> pd.Series:
    """Find swing highs in a series."""
    roll_max = series.rolling(window=2 * order + 1, center=True).max()
    return pd.Series(np.where(series == roll_max, series, np.nan), index=series.index)

def swing_lows(series: pd.Series, order: int = 5) -> pd.Series:
    """Find swing lows in a series."""
    roll_min = series.rolling(window=2 * order + 1, center=True).min()
    return pd.Series(np.where(series == roll_min, series, np.nan), index=series.index)

def higher_highs(series: pd.Series, order: int = 5) -> pd.Series:
    """Find higher highs."""
    highs = swing_highs(series, order)
    valid_highs = highs.dropna()
    is_hh = valid_highs > valid_highs.shift(1)
    res = pd.Series(False, index=series.index)
    if not is_hh.empty:
        res.loc[is_hh[is_hh].index] = True
    return res

def lower_highs(series: pd.Series, order: int = 5) -> pd.Series:
    """Find lower highs."""
    highs = swing_highs(series, order)
    valid_highs = highs.dropna()
    is_lh = valid_highs < valid_highs.shift(1)
    res = pd.Series(False, index=series.index)
    if not is_lh.empty:
        res.loc[is_lh[is_lh].index] = True
    return res

def higher_lows(series: pd.Series, order: int = 5) -> pd.Series:
    """Find higher lows."""
    lows = swing_lows(series, order)
    valid_lows = lows.dropna()
    is_hl = valid_lows > valid_lows.shift(1)
    res = pd.Series(False, index=series.index)
    if not is_hl.empty:
        res.loc[is_hl[is_hl].index] = True
    return res

def lower_lows(series: pd.Series, order: int = 5) -> pd.Series:
    """Find lower lows."""
    lows = swing_lows(series, order)
    valid_lows = lows.dropna()
    is_ll = valid_lows < valid_lows.shift(1)
    res = pd.Series(False, index=series.index)
    if not is_ll.empty:
        res.loc[is_ll[is_ll].index] = True
    return res


def find_swings(high: pd.Series, low: pd.Series, window: int = 5) -> pd.DataFrame:
    """Find local swing highs and lows."""
    # A point is a swing high if it's the highest in the window before and after it
    roll_high = high.rolling(window=2*window+1, center=True).max()
    roll_low = low.rolling(window=2*window+1, center=True).min()
    
    is_swing_high = (high == roll_high)
    is_swing_low = (low == roll_low)
    
    return pd.DataFrame({
        'swing_high': is_swing_high,
        'swing_low': is_swing_low,
        'swing_high_price': high.where(is_swing_high),
        'swing_low_price': low.where(is_swing_low)
    }, index=high.index)


@register_indicator(
    name="trend_structure",
    category="PATTERN",
    inputs=["high", "low"],
    outputs=["HH", "LH", "HL", "LL", "uptrend", "downtrend"],
    parameters={"window": 5}
)
def trend_structure(high: pd.Series, low: pd.Series, window: int = 5) -> pd.DataFrame:
    """
    Determine Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), Lower Lows (LL).
    
    This function identifies the trend structure based on swing highs and lows,
    following Dow Theory principles. An uptrend is characterized by higher highs
    and higher lows, while a downtrend is characterized by lower highs and lower lows.
    
    Args:
        high (pd.Series): High prices.
        low (pd.Series): Low prices.
        window (int): The window size for identifying swings.
        
    Returns:
        pd.DataFrame: A DataFrame containing boolean columns for HH, LH, HL, LL,
            as well as uptrend and downtrend state indicators.
    """
    swings = find_swings(high, low, window)
    
    # Forward fill the last known swing prices
    last_high = swings['swing_high_price'].ffill()
    last_low = swings['swing_low_price'].ffill()
    
    # Previous known swings
    prev_high = last_high.shift(1).ffill()
    prev_low = last_low.shift(1).ffill()
    
    df = pd.DataFrame(index=high.index)
    df['HH'] = swings['swing_high'] & (swings['swing_high_price'] > prev_high)
    df['LH'] = swings['swing_high'] & (swings['swing_high_price'] < prev_high)
    df['HL'] = swings['swing_low'] & (swings['swing_low_price'] > prev_low)
    df['LL'] = swings['swing_low'] & (swings['swing_low_price'] < prev_low)
    
    # State tracking: uptrend requires latest completed swing high to be HH and low to be HL
    # For this, we forward fill the boolean flags of the latest swing
    last_is_hh = df['HH'].where(swings['swing_high']).ffill().fillna(False)
    last_is_hl = df['HL'].where(swings['swing_low']).ffill().fillna(False)
    last_is_lh = df['LH'].where(swings['swing_high']).ffill().fillna(False)
    last_is_ll = df['LL'].where(swings['swing_low']).ffill().fillna(False)
    
    df['uptrend'] = last_is_hh & last_is_hl
    df['downtrend'] = last_is_lh & last_is_ll
    
    return df

def trend_change(df: pd.DataFrame, order: int = 5) -> pd.Series:
    """Determine trend changes (-1, 0, 1) based on Dow Theory."""
    ts = trend_structure(df['high'], df['low'], window=order)
    res = pd.Series(0, index=df.index)
    res.loc[ts['uptrend']] = 1
    res.loc[ts['downtrend']] = -1
    return res

def market_phase(df: pd.DataFrame, lookback: int = 200) -> pd.Series:
    """
    Identify Wyckoff market phases.
    
    Returns:
        1: Accumulation
        2: Markup
        3: Distribution
        4: Markdown
    """
    close = df['close']
    fast = close.rolling(50).mean()
    slow = close.rolling(lookback).mean()
    
    phase = pd.Series(0, index=df.index)
    # Markup
    phase[(close > fast) & (fast > slow)] = 2
    # Markdown
    phase[(close < fast) & (fast < slow)] = 4
    # Accumulation
    phase[(close > fast) & (fast <= slow)] = 1
    # Distribution
    phase[(close < fast) & (fast >= slow)] = 3
    
    return phase

__all__ = [
    "swing_highs", "swing_lows", "higher_highs", "lower_highs", "higher_lows", "lower_lows",
    "find_swings", "trend_structure", "trend_change", "market_phase"
]
