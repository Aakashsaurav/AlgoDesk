"""
indicators/patterns/dow_patterns.py
-----------------------------------
Dow Theory patterns (higher highs, lower lows).
"""
import pandas as pd
from indicators.registry import register_indicator


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
    """Determine Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), Lower Lows (LL)."""
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

__all__ = ["find_swings", "trend_structure"]
