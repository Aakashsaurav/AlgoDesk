"""
indicators/patterns/chart_patterns.py
-------------------------------------
Chart pattern recognition (triangles, double tops/bottoms).
"""
import numpy as np
import pandas as pd
from typing import Tuple

from indicators.registry import register_indicator

def _find_swing_highs(high: pd.Series, window: int = 5) -> pd.Series:
    """Find swing highs."""
    roll_max = high.rolling(window=2 * window + 1, center=True).max()
    return pd.Series(np.where(high == roll_max, high, np.nan), index=high.index)

def _find_swing_lows(low: pd.Series, window: int = 5) -> pd.Series:
    """Find swing lows."""
    roll_min = low.rolling(window=2 * window + 1, center=True).min()
    return pd.Series(np.where(low == roll_min, low, np.nan), index=low.index)

def _fit_trendline(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """Fit a linear trendline y = mx + c. Returns (m, c)."""
    if len(x) < 2:
        return 0.0, 0.0
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    denominator = np.sum((x - x_mean) ** 2)
    if denominator == 0:
        return 0.0, 0.0
    m = np.sum((x - x_mean) * (y - y_mean)) / denominator
    c = y_mean - m * x_mean
    return m, c

def _lines_converge(slope1: float, slope2: float, tolerance: float = 0.01) -> bool:
    """Check if lines are converging."""
    return (slope1 < -tolerance and slope2 > tolerance) or \
           (abs(slope1) < tolerance and slope2 > tolerance) or \
           (slope1 < -tolerance and abs(slope2) < tolerance) or \
           (slope1 > 0 and slope2 > 0 and slope1 < slope2) or \
           (slope1 < 0 and slope2 < 0 and slope1 < slope2)

def _lines_diverge(slope1: float, slope2: float, tolerance: float = 0.01) -> bool:
    """Check if lines are diverging."""
    return (slope1 > tolerance and slope2 < -tolerance)

def _get_recent_swings(swings: pd.Series, n: int = 3) -> pd.DataFrame:
    df = pd.DataFrame(index=swings.index)
    for i in range(1, n + 1):
        df[f'val_{i}'] = np.nan
        df[f'idx_{i}'] = np.nan
        
    valid_swings = swings.dropna()
    if valid_swings.empty:
        return df
        
    pos_idx = np.arange(len(swings))
    valid_pos = pos_idx[swings.notna()]
    swing_df = pd.DataFrame({'val': valid_swings, 'idx': valid_pos}, index=valid_swings.index)
    
    for i in range(1, n + 1):
        shifted = swing_df.shift(i - 1)
        df[f'val_{i}'] = shifted['val']
        df[f'idx_{i}'] = shifted['idx']
        
    return df.ffill()

def triangle_ascending(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify ascending triangle patterns (flat top, rising bottom)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_flat_top = (np.abs(h1 - h2) / np.maximum(h1, 1e-5)) < 0.02
    cond_rising_bottom = l1 > (l2 * 1.005)
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    top_line = h1 + slope_top * (curr_idx - h1_idx)
    top_line_prev = top_line - slope_top
    
    cond_breakout = (close > top_line) & (close.shift(1) <= top_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    is_pattern = cond_flat_top & cond_rising_bottom & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = 1
    return res

def triangle_descending(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify descending triangle patterns (falling top, flat bottom)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_flat_bottom = (np.abs(l1 - l2) / np.maximum(l1, 1e-5)) < 0.02
    cond_falling_top = h1 < (h2 * 0.995)
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    bottom_line = l1 + slope_bottom * (curr_idx - l1_idx)
    bottom_line_prev = bottom_line - slope_bottom
    
    cond_breakout = (close < bottom_line) & (close.shift(1) >= bottom_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    is_pattern = cond_flat_bottom & cond_falling_top & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = -1
    return res

def triangle_symmetrical(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify symmetrical triangle patterns (converging trendlines)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_converge = (slope_top < 0) & (slope_bottom > 0)
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    top_line = h1 + slope_top * (curr_idx - h1_idx)
    top_line_prev = top_line - slope_top
    
    bottom_line = l1 + slope_bottom * (curr_idx - l1_idx)
    bottom_line_prev = bottom_line - slope_bottom
    
    cond_breakout_up = (close > top_line) & (close.shift(1) <= top_line_prev)
    cond_breakout_down = (close < bottom_line) & (close.shift(1) >= bottom_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    res = pd.Series(0, index=close.index)
    res[cond_converge & cond_time & cond_breakout_up] = 1
    res[cond_converge & cond_time & cond_breakout_down] = -1
    return res

def flag_bullish(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify bullish flag patterns (downward parallel channel)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_downward = (slope_top < 0) & (slope_bottom < 0)
    cond_parallel = (np.abs(slope_top - slope_bottom) / np.maximum(np.abs(slope_top), 1e-5)) < 0.5
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    top_line = h1 + slope_top * (curr_idx - h1_idx)
    top_line_prev = top_line - slope_top
    
    cond_breakout = (close > top_line) & (close.shift(1) <= top_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    is_pattern = cond_downward & cond_parallel & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = 1
    return res

def flag_bearish(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify bearish flag patterns (upward parallel channel)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_upward = (slope_top > 0) & (slope_bottom > 0)
    cond_parallel = (np.abs(slope_top - slope_bottom) / np.maximum(np.abs(slope_top), 1e-5)) < 0.5
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    bottom_line = l1 + slope_bottom * (curr_idx - l1_idx)
    bottom_line_prev = bottom_line - slope_bottom
    
    cond_breakout = (close < bottom_line) & (close.shift(1) >= bottom_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    is_pattern = cond_upward & cond_parallel & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = -1
    return res

def pennant(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 3) -> pd.Series:
    """Identify pennant patterns (small symmetrical triangle)."""
    return triangle_symmetrical(high, low, close, window)

def wedge_rising(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify rising wedge patterns (converging upward trendlines)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_rising = (slope_top > 0) & (slope_bottom > 0)
    cond_converge = slope_bottom > slope_top
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    bottom_line = l1 + slope_bottom * (curr_idx - l1_idx)
    bottom_line_prev = bottom_line - slope_bottom
    
    cond_breakout = (close < bottom_line) & (close.shift(1) >= bottom_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    is_pattern = cond_rising & cond_converge & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = -1
    return res

def wedge_falling(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify falling wedge patterns (converging downward trendlines)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope_top = (h1 - h2) / d_h
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope_bottom = (l1 - l2) / d_l
    
    cond_falling = (slope_top < 0) & (slope_bottom < 0)
    cond_converge = slope_top < slope_bottom
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    top_line = h1 + slope_top * (curr_idx - h1_idx)
    top_line_prev = top_line - slope_top
    
    cond_breakout = (close > top_line) & (close.shift(1) <= top_line_prev)
    cond_time = (curr_idx > np.maximum(h1_idx, l1_idx))
    
    is_pattern = cond_falling & cond_converge & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = 1
    return res

def double_top(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify double top patterns (two similar highs with a dip between)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 2)
    rl = _get_recent_swings(lows, 1)
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    l1 = rl['val_1']
    l1_idx = rl['idx_1']
    
    cond_height = (np.abs(h1 - h2) / np.maximum(h1, 1e-5)) < 0.03
    cond_order = (h1_idx > l1_idx) & (l1_idx > h2_idx)
    
    cond_breakout = (close < l1) & (close.shift(1) >= l1)
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    cond_time = curr_idx > h1_idx
    
    is_pattern = cond_height & cond_order & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = -1
    return res

def double_bottom(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify double bottom patterns (two similar lows with a bounce between)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rl = _get_recent_swings(lows, 2)
    rh = _get_recent_swings(highs, 1)
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    h1 = rh['val_1']
    h1_idx = rh['idx_1']
    
    cond_height = (np.abs(l1 - l2) / np.maximum(l1, 1e-5)) < 0.03
    cond_order = (l1_idx > h1_idx) & (h1_idx > l2_idx)
    
    cond_breakout = (close > h1) & (close.shift(1) <= h1)
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    cond_time = curr_idx > l1_idx
    
    is_pattern = cond_height & cond_order & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = 1
    return res

def head_and_shoulders(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify head and shoulders patterns (three peaks, middle is highest)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 3)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2, h3 = rh['val_1'], rh['val_2'], rh['val_3']
    h1_idx, h2_idx, h3_idx = rh['idx_1'], rh['idx_2'], rh['idx_3']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    cond_head = (h2 > h1) & (h2 > h3)
    cond_shoulders = (np.abs(h1 - h3) / np.maximum(np.maximum(h1, h3), 1e-5)) < 0.05
    cond_order = (h1_idx > l1_idx) & (l1_idx > h2_idx) & (h2_idx > l2_idx) & (l2_idx > h3_idx)
    
    d_l = (l1_idx - l2_idx).clip(lower=1)
    slope = (l1 - l2) / d_l
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    neckline = l1 + slope * (curr_idx - l1_idx)
    neckline_prev = neckline - slope
    
    cond_breakout = (close < neckline) & (close.shift(1) >= neckline_prev)
    cond_time = curr_idx > h1_idx
    
    is_pattern = cond_head & cond_shoulders & cond_order & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = -1
    return res

def inverse_head_and_shoulders(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify inverse head and shoulders patterns (three troughs, middle is lowest)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rl = _get_recent_swings(lows, 3)
    rh = _get_recent_swings(highs, 2)
    
    l1, l2, l3 = rl['val_1'], rl['val_2'], rl['val_3']
    l1_idx, l2_idx, l3_idx = rl['idx_1'], rl['idx_2'], rl['idx_3']
    
    h1, h2 = rh['val_1'], rh['val_2']
    h1_idx, h2_idx = rh['idx_1'], rh['idx_2']
    
    cond_head = (l2 < l1) & (l2 < l3)
    cond_shoulders = (np.abs(l1 - l3) / np.maximum(np.maximum(l1, l3), 1e-5)) < 0.05
    cond_order = (l1_idx > h1_idx) & (h1_idx > l2_idx) & (l2_idx > h2_idx) & (h2_idx > l3_idx)
    
    d_h = (h1_idx - h2_idx).clip(lower=1)
    slope = (h1 - h2) / d_h
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    neckline = h1 + slope * (curr_idx - h1_idx)
    neckline_prev = neckline - slope
    
    cond_breakout = (close > neckline) & (close.shift(1) <= neckline_prev)
    cond_time = curr_idx > l1_idx
    
    is_pattern = cond_head & cond_shoulders & cond_order & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = 1
    return res

def cup_and_handle(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 5) -> pd.Series:
    """Identify cup and handle patterns (U-shape cup followed by slight downward drift)."""
    highs = _find_swing_highs(high, window)
    lows = _find_swing_lows(low, window)
    
    rh = _get_recent_swings(highs, 3)
    rl = _get_recent_swings(lows, 2)
    
    h1, h2, h3 = rh['val_1'], rh['val_2'], rh['val_3']
    h1_idx, h2_idx, h3_idx = rh['idx_1'], rh['idx_2'], rh['idx_3']
    
    l1, l2 = rl['val_1'], rl['val_2']
    l1_idx, l2_idx = rl['idx_1'], rl['idx_2']
    
    cond_lips = (np.abs(h3 - h2) / np.maximum(np.maximum(h3, h2), 1e-5)) < 0.05
    cond_handle_high = h1 < h2
    cond_cup_depth = (h2 - l2) / np.maximum(h2, 1e-5) > 0.05
    cond_handle_low = l1 > (l2 + (h2 - l2) * 0.3)
    
    cond_order = (h1_idx > l1_idx) & (l1_idx > h2_idx) & (h2_idx > l2_idx) & (l2_idx > h3_idx)
    
    curr_idx = pd.Series(np.arange(len(close)), index=close.index)
    cond_breakout = (close > h2) & (close.shift(1) <= h2)
    cond_time = curr_idx > h1_idx
    
    is_pattern = cond_lips & cond_handle_high & cond_cup_depth & cond_handle_low & cond_order & cond_breakout & cond_time
    res = pd.Series(0, index=close.index)
    res[is_pattern] = 1
    return res

@register_indicator(
    name="scan_all_chart",
    category="PATTERN",
    inputs=["high", "low", "close"],
    outputs=[
        "triangle_ascending", "triangle_descending", "triangle_symmetrical",
        "flag_bullish", "flag_bearish", "pennant", "wedge_rising", "wedge_falling",
        "double_top", "double_bottom", "head_and_shoulders", "inverse_head_and_shoulders",
        "cup_and_handle"
    ]
)
def scan_all_chart(df: pd.DataFrame) -> pd.DataFrame:
    """Scan for common chart patterns."""
    res = pd.DataFrame(index=df.index)
    
    if len(df) == 0:
        for col in ["triangle_ascending", "triangle_descending", "triangle_symmetrical",
                    "flag_bullish", "flag_bearish", "pennant", "wedge_rising", "wedge_falling",
                    "double_top", "double_bottom", "head_and_shoulders", "inverse_head_and_shoulders",
                    "cup_and_handle"]:
            res[col] = 0
        return res

    high = df['high']
    low = df['low']
    close = df['close']
    
    res['triangle_ascending'] = triangle_ascending(high, low, close)
    res['triangle_descending'] = triangle_descending(high, low, close)
    res['triangle_symmetrical'] = triangle_symmetrical(high, low, close)
    res['flag_bullish'] = flag_bullish(high, low, close)
    res['flag_bearish'] = flag_bearish(high, low, close)
    res['pennant'] = pennant(high, low, close)
    res['wedge_rising'] = wedge_rising(high, low, close)
    res['wedge_falling'] = wedge_falling(high, low, close)
    res['double_top'] = double_top(high, low, close)
    res['double_bottom'] = double_bottom(high, low, close)
    res['head_and_shoulders'] = head_and_shoulders(high, low, close)
    res['inverse_head_and_shoulders'] = inverse_head_and_shoulders(high, low, close)
    res['cup_and_handle'] = cup_and_handle(high, low, close)
    
    return res

__all__ = [
    "triangle_ascending", "triangle_descending", "triangle_symmetrical",
    "flag_bullish", "flag_bearish", "pennant", "wedge_rising", "wedge_falling",
    "double_top", "double_bottom", "head_and_shoulders", "inverse_head_and_shoulders",
    "cup_and_handle", "scan_all_chart"
]
