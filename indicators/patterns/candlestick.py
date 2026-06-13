"""
indicators/patterns/candlestick.py
----------------------------------
Candlestick pattern recognition.
Delegates to TA-Lib with a pure pandas fallback for core patterns.
"""
from typing import Callable
import pandas as pd
import numpy as np
from indicators.bridge import LibraryStatus
from indicators.registry import register_indicator


def _normalize_talib_output(series: pd.Series) -> pd.Series:
    """Normalize TA-Lib output from 100/-100 or 200/-200 to 1/-1/0."""
    return np.sign(series)


def _auto_select(
    df: pd.DataFrame,
    talib_func_name: str,
    fallback_func: Callable[[pd.DataFrame], pd.Series]
) -> pd.Series:
    if LibraryStatus.check("talib"):
        import talib
        func = getattr(talib, talib_func_name, None)
        if func is not None:
            op = df['open'].values.astype(float)
            hi = df['high'].values.astype(float)
            lo = df['low'].values.astype(float)
            cl = df['close'].values.astype(float)
            res = pd.Series(func(op, hi, lo, cl), index=df.index)
            return _normalize_talib_output(res).astype(int)
    
    # fallback
    res = fallback_func(df)
    return res.fillna(0).astype(int)


def get_candle_features(df: pd.DataFrame):
    o, h, l, c = df['open'], df['high'], df['low'], df['close']
    body = (c - o).abs()
    real_body_top = pd.concat([o, c], axis=1).max(axis=1)
    real_body_bottom = pd.concat([o, c], axis=1).min(axis=1)
    upper_shadow = h - real_body_top
    lower_shadow = real_body_bottom - l
    rng = h - l
    is_bullish = c > o
    is_bearish = c < o
    return body, upper_shadow, lower_shadow, rng, is_bullish, is_bearish, real_body_top, real_body_bottom


@register_indicator(name="doji", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["doji"])
def doji(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return (body <= rng * 0.1).astype(int)
    res = _auto_select(df, "CDLDOJI", fallback)
    return (res == 1).astype(int)


@register_indicator(name="hammer", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["hammer"])
def hammer(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return ((ls >= 2 * body) & (us <= rng * 0.1) & (rng > 0)).astype(int)
    res = _auto_select(df, "CDLHAMMER", fallback)
    return (res == 1).astype(int)


@register_indicator(name="hanging_man", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["hanging_man"])
def hanging_man(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return ((ls >= 2 * body) & (us <= rng * 0.1) & (body > 0)).astype(int) * -1
    return _auto_select(df, "CDLHANGINGMAN", fallback)


@register_indicator(name="inverted_hammer", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["inverted_hammer"])
def inverted_hammer(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return ((us >= 2 * body) & (ls <= rng * 0.1) & (body > 0)).astype(int)
    return _auto_select(df, "CDLINVERTEDHAMMER", fallback)


@register_indicator(name="shooting_star", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["shooting_star"])
def shooting_star(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return ((us >= 2 * body) & (ls <= rng * 0.1) & (body > 0)).astype(int) * -1
    return _auto_select(df, "CDLSHOOTINGSTAR", fallback)


def _engulfing_fallback(df: pd.DataFrame) -> pd.Series:
    body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
    prev_bull = bull.shift(1)
    prev_bear = bear.shift(1)
    prev_body = body.shift(1)
    is_bull_eng = prev_bear & bull & (body > prev_body) & (rt > rt.shift(1)) & (rb < rb.shift(1))
    is_bear_eng = prev_bull & bear & (body > prev_body) & (rb < rb.shift(1)) & (rt > rt.shift(1))
    return is_bull_eng.astype(int) - is_bear_eng.astype(int)


@register_indicator(name="bullish_engulfing", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["bullish_engulfing"])
def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    res = _auto_select(df, "CDLENGULFING", _engulfing_fallback)
    return (res == 1).astype(int)


@register_indicator(name="bearish_engulfing", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["bearish_engulfing"])
def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    res = _auto_select(df, "CDLENGULFING", _engulfing_fallback)
    return (res == -1).astype(int)


@register_indicator(name="morning_star", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["morning_star"])
def morning_star(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return (bear.shift(2) & (body.shift(1) <= rng.shift(1) * 0.3) & bull & (df['close'] > (df['open'].shift(2) + df['close'].shift(2)) / 2)).astype(int)
    return _auto_select(df, "CDLMORNINGSTAR", fallback)


@register_indicator(name="evening_star", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["evening_star"])
def evening_star(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return (bull.shift(2) & (body.shift(1) <= rng.shift(1) * 0.3) & bear & (df['close'] < (df['open'].shift(2) + df['close'].shift(2)) / 2)).astype(int) * -1
    return _auto_select(df, "CDLEVENINGSTAR", fallback)


@register_indicator(name="three_white_soldiers", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_white_soldiers"])
def three_white_soldiers(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return (bull & bull.shift(1) & bull.shift(2) & (df['close'] > df['close'].shift(1)) & (df['close'].shift(1) > df['close'].shift(2))).astype(int)
    return _auto_select(df, "CDL3WHITESOLDIERS", fallback)


@register_indicator(name="three_black_crows", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_black_crows"])
def three_black_crows(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return (bear & bear.shift(1) & bear.shift(2) & (df['close'] < df['close'].shift(1)) & (df['close'].shift(1) < df['close'].shift(2))).astype(int) * -1
    return _auto_select(df, "CDL3BLACKCROWS", fallback)


@register_indicator(name="marubozu", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["marubozu"])
def marubozu(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        is_bull_maru = bull & (us <= rng * 0.05) & (ls <= rng * 0.05) & (body > 0)
        is_bear_maru = bear & (us <= rng * 0.05) & (ls <= rng * 0.05) & (body > 0)
        return is_bull_maru.astype(int) - is_bear_maru.astype(int)
    return _auto_select(df, "CDLMARUBOZU", fallback)


@register_indicator(name="dragonfly_doji", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["dragonfly_doji"])
def dragonfly_doji(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return ((body <= rng * 0.1) & (us <= rng * 0.1) & (ls > rng * 0.5)).astype(int)
    return _auto_select(df, "CDLDRAGONFLYDOJI", fallback)


@register_indicator(name="gravestone_doji", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["gravestone_doji"])
def gravestone_doji(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        return ((body <= rng * 0.1) & (ls <= rng * 0.1) & (us > rng * 0.5)).astype(int)
    return _auto_select(df, "CDLGRAVESTONEDOJI", fallback)


@register_indicator(name="harami", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["harami"])
def harami(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        is_bull_harami = bear.shift(1) & bull & (rt < rt.shift(1)) & (rb > rb.shift(1))
        is_bear_harami = bull.shift(1) & bear & (rt < rt.shift(1)) & (rb > rb.shift(1))
        return is_bull_harami.astype(int) - is_bear_harami.astype(int)
    return _auto_select(df, "CDLHARAMI", fallback)


@register_indicator(name="harami_cross", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["harami_cross"])
def harami_cross(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        is_doji = body <= rng * 0.1
        is_bull_harami = bear.shift(1) & is_doji & (rt < rt.shift(1)) & (rb > rb.shift(1))
        is_bear_harami = bull.shift(1) & is_doji & (rt < rt.shift(1)) & (rb > rb.shift(1))
        return is_bull_harami.astype(int) - is_bear_harami.astype(int)
    return _auto_select(df, "CDLHARAMICROSS", fallback)


@register_indicator(name="piercing_pattern", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["piercing_pattern"])
def piercing_pattern(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        midpoint_prev = (df['open'].shift(1) + df['close'].shift(1)) / 2
        return (bear.shift(1) & bull & (df['open'] < rb.shift(1)) & (df['close'] > midpoint_prev) & (df['close'] < rt.shift(1))).astype(int)
    return _auto_select(df, "CDLPIERCING", fallback)


@register_indicator(name="dark_cloud_cover", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["dark_cloud_cover"])
def dark_cloud_cover(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        midpoint_prev = (df['open'].shift(1) + df['close'].shift(1)) / 2
        return (bull.shift(1) & bear & (df['open'] > rt.shift(1)) & (df['close'] < midpoint_prev) & (df['close'] > rb.shift(1))).astype(int) * -1
    return _auto_select(df, "CDLDARKCLOUDCOVER", fallback)


@register_indicator(name="spinning_top", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["spinning_top"])
def spinning_top(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        is_spinning = (body <= rng * 0.3) & (us > body) & (ls > body)
        return is_spinning.astype(int) * (bull.astype(int) - bear.astype(int))
    return _auto_select(df, "CDLSPINNINGTOP", fallback)


@register_indicator(name="tweezer_top", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["tweezer_top"])
def tweezer_top(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        is_tweezer = ((df['high'] - df['high'].shift(1)).abs() < (df['high'] * 0.0001)) & (df['close'] < df['open'])
        return is_tweezer.astype(int) * -1
    return _auto_select(df, "CDLTWEEZERTOP", fallback)


@register_indicator(name="tweezer_bottom", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["tweezer_bottom"])
def tweezer_bottom(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        is_tweezer = ((df['low'] - df['low'].shift(1)).abs() < (df['low'] * 0.0001)) & (df['close'] > df['open'])
        return is_tweezer.astype(int)
    return _auto_select(df, "CDLTWEEZERBOTTOM", fallback)


@register_indicator(name="abandoned_baby", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["abandoned_baby"])
def abandoned_baby(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        is_doji = body.shift(1) <= rng.shift(1) * 0.1
        bull_baby = bear.shift(2) & is_doji & bull & (df['low'].shift(1) < df['low'].shift(2)) & (df['low'].shift(1) < df['low']) & (df['high'].shift(1) < df['low'].shift(2)) & (df['high'].shift(1) < df['low'])
        bear_baby = bull.shift(2) & is_doji & bear & (df['high'].shift(1) > df['high'].shift(2)) & (df['high'].shift(1) > df['high']) & (df['low'].shift(1) > df['high'].shift(2)) & (df['low'].shift(1) > df['high'])
        return bull_baby.astype(int) - bear_baby.astype(int)
    return _auto_select(df, "CDLABANDONEDBABY", fallback)


def _three_inside_fallback(df: pd.DataFrame) -> pd.Series:
    body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
    is_bull_harami = bear.shift(2) & bull.shift(1) & (rt.shift(1) < rt.shift(2)) & (rb.shift(1) > rb.shift(2))
    three_up = is_bull_harami & bull & (df['close'] > df['close'].shift(1))
    is_bear_harami = bull.shift(2) & bear.shift(1) & (rt.shift(1) < rt.shift(2)) & (rb.shift(1) > rb.shift(2))
    three_down = is_bear_harami & bear & (df['close'] < df['close'].shift(1))
    return three_up.astype(int) - three_down.astype(int)


@register_indicator(name="three_inside_up", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_inside_up"])
def three_inside_up(df: pd.DataFrame) -> pd.Series:
    res = _auto_select(df, "CDL3INSIDE", _three_inside_fallback)
    return (res == 1).astype(int)


@register_indicator(name="three_inside_down", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_inside_down"])
def three_inside_down(df: pd.DataFrame) -> pd.Series:
    res = _auto_select(df, "CDL3INSIDE", _three_inside_fallback)
    return (res == -1).astype(int)


def _three_outside_fallback(df: pd.DataFrame) -> pd.Series:
    body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
    is_bull_eng = bear.shift(2) & bull.shift(1) & (body.shift(1) > body.shift(2)) & (rt.shift(1) > rt.shift(2)) & (rb.shift(1) < rb.shift(2))
    three_up = is_bull_eng & bull & (df['close'] > df['close'].shift(1))
    is_bear_eng = bull.shift(2) & bear.shift(1) & (body.shift(1) > body.shift(2)) & (rb.shift(1) < rb.shift(2)) & (rt.shift(1) > rt.shift(2))
    three_down = is_bear_eng & bear & (df['close'] < df['close'].shift(1))
    return three_up.astype(int) - three_down.astype(int)


@register_indicator(name="three_outside_up", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_outside_up"])
def three_outside_up(df: pd.DataFrame) -> pd.Series:
    res = _auto_select(df, "CDL3OUTSIDE", _three_outside_fallback)
    return (res == 1).astype(int)


@register_indicator(name="three_outside_down", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_outside_down"])
def three_outside_down(df: pd.DataFrame) -> pd.Series:
    res = _auto_select(df, "CDL3OUTSIDE", _three_outside_fallback)
    return (res == -1).astype(int)


@register_indicator(name="kicking", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["kicking"])
def kicking(df: pd.DataFrame) -> pd.Series:
    def fallback(df):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(df)
        is_bull_maru_prev = bear.shift(1) & (us.shift(1) <= rng.shift(1) * 0.05) & (ls.shift(1) <= rng.shift(1) * 0.05)
        is_bull_maru = bull & (us <= rng * 0.05) & (ls <= rng * 0.05)
        bull_kick = is_bull_maru_prev & is_bull_maru & (df['open'] > df['open'].shift(1))
        
        is_bear_maru_prev = bull.shift(1) & (us.shift(1) <= rng.shift(1) * 0.05) & (ls.shift(1) <= rng.shift(1) * 0.05)
        is_bear_maru = bear & (us <= rng * 0.05) & (ls <= rng * 0.05)
        bear_kick = is_bear_maru_prev & is_bear_maru & (df['open'] < df['open'].shift(1))
        
        return bull_kick.astype(int) - bear_kick.astype(int)
    return _auto_select(df, "CDLKICKING", fallback)


@register_indicator(
    name="scan_all_candlestick",
    category="PATTERN",
    inputs=["open", "high", "low", "close"],
    outputs=["doji", "engulfing", "hammer", "morning_star", "shooting_star"]
)
def scan_all_candlestick(df: pd.DataFrame) -> pd.DataFrame:
    """Scan for common candlestick patterns."""
    res = pd.DataFrame(index=df.index)
    res['doji'] = doji(df)
    res['engulfing'] = bullish_engulfing(df) - bearish_engulfing(df)
    res['hammer'] = hammer(df)
    res['morning_star'] = morning_star(df)
    res['shooting_star'] = shooting_star(df)
    return res


__all__ = [
    "doji",
    "hammer",
    "hanging_man",
    "inverted_hammer",
    "shooting_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "morning_star",
    "evening_star",
    "three_white_soldiers",
    "three_black_crows",
    "marubozu",
    "dragonfly_doji",
    "gravestone_doji",
    "harami",
    "harami_cross",
    "piercing_pattern",
    "dark_cloud_cover",
    "spinning_top",
    "tweezer_top",
    "tweezer_bottom",
    "abandoned_baby",
    "three_inside_up",
    "three_inside_down",
    "three_outside_up",
    "three_outside_down",
    "kicking",
    "scan_all_candlestick"
]
