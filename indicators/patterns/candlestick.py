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
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    talib_func_name: str,
    fallback_func: Callable[[pd.Series, pd.Series, pd.Series, pd.Series], pd.Series]
) -> pd.Series:
    if LibraryStatus.check("talib"):
        import talib
        func = getattr(talib, talib_func_name, None)
        if func is not None:
            op = open_.values.astype(float)
            hi = high.values.astype(float)
            lo = low.values.astype(float)
            cl = close.values.astype(float)
            res = pd.Series(func(op, hi, lo, cl), index=close.index)
            return _normalize_talib_output(res).astype(int)
    
    # fallback
    res = fallback_func(open_, high, low, close)
    return res.fillna(0).astype(int)


def get_candle_features(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series):
    o, h, l, c = open_, high, low, close
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
def doji(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return (body <= rng * 0.1).astype(int)
    res = _auto_select(open_, high, low, close, "CDLDOJI", fallback)
    return (res == 1).astype(int)


@register_indicator(name="hammer", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["hammer"])
def hammer(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return ((ls >= 2 * body) & (us <= rng * 0.1) & (rng > 0)).astype(int)
    res = _auto_select(open_, high, low, close, "CDLHAMMER", fallback)
    return (res == 1).astype(int)


@register_indicator(name="hanging_man", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["hanging_man"])
def hanging_man(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return ((ls >= 2 * body) & (us <= rng * 0.1) & (body > 0)).astype(int) * -1
    return _auto_select(open_, high, low, close, "CDLHANGINGMAN", fallback)


@register_indicator(name="inverted_hammer", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["inverted_hammer"])
def inverted_hammer(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return ((us >= 2 * body) & (ls <= rng * 0.1) & (body > 0)).astype(int)
    return _auto_select(open_, high, low, close, "CDLINVERTEDHAMMER", fallback)


@register_indicator(name="shooting_star", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["shooting_star"])
def shooting_star(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return ((us >= 2 * body) & (ls <= rng * 0.1) & (body > 0)).astype(int) * -1
    return _auto_select(open_, high, low, close, "CDLSHOOTINGSTAR", fallback)


def _engulfing_fallback(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
    prev_bull = bull.shift(1)
    prev_bear = bear.shift(1)
    prev_body = body.shift(1)
    is_bull_eng = prev_bear & bull & (body > prev_body) & (rt > rt.shift(1)) & (rb < rb.shift(1))
    is_bear_eng = prev_bull & bear & (body > prev_body) & (rb < rb.shift(1)) & (rt > rt.shift(1))
    return is_bull_eng.astype(int) - is_bear_eng.astype(int)


@register_indicator(name="bullish_engulfing", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["bullish_engulfing"])
def bullish_engulfing(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    res = _auto_select(open_, high, low, close, "CDLENGULFING", _engulfing_fallback)
    return (res == 1).astype(int)


@register_indicator(name="bearish_engulfing", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["bearish_engulfing"])
def bearish_engulfing(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    res = _auto_select(open_, high, low, close, "CDLENGULFING", _engulfing_fallback)
    return (res == -1).astype(int)


@register_indicator(name="morning_star", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["morning_star"])
def morning_star(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return (bear.shift(2) & (body.shift(1) <= rng.shift(1) * 0.3) & bull & (close > (open_.shift(2) + close.shift(2)) / 2)).astype(int)
    return _auto_select(open_, high, low, close, "CDLMORNINGSTAR", fallback)


@register_indicator(name="evening_star", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["evening_star"])
def evening_star(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return (bull.shift(2) & (body.shift(1) <= rng.shift(1) * 0.3) & bear & (close < (open_.shift(2) + close.shift(2)) / 2)).astype(int) * -1
    return _auto_select(open_, high, low, close, "CDLEVENINGSTAR", fallback)


@register_indicator(name="three_white_soldiers", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_white_soldiers"])
def three_white_soldiers(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return (bull & bull.shift(1) & bull.shift(2) & (close > close.shift(1)) & (close.shift(1) > close.shift(2))).astype(int)
    return _auto_select(open_, high, low, close, "CDL3WHITESOLDIERS", fallback)


@register_indicator(name="three_black_crows", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_black_crows"])
def three_black_crows(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return (bear & bear.shift(1) & bear.shift(2) & (close < close.shift(1)) & (close.shift(1) < close.shift(2))).astype(int) * -1
    return _auto_select(open_, high, low, close, "CDL3BLACKCROWS", fallback)


@register_indicator(name="marubozu", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["marubozu"])
def marubozu(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        is_bull_maru = bull & (us <= rng * 0.05) & (ls <= rng * 0.05) & (body > 0)
        is_bear_maru = bear & (us <= rng * 0.05) & (ls <= rng * 0.05) & (body > 0)
        return is_bull_maru.astype(int) - is_bear_maru.astype(int)
    return _auto_select(open_, high, low, close, "CDLMARUBOZU", fallback)


@register_indicator(name="dragonfly_doji", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["dragonfly_doji"])
def dragonfly_doji(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return ((body <= rng * 0.1) & (us <= rng * 0.1) & (ls > rng * 0.5)).astype(int)
    return _auto_select(open_, high, low, close, "CDLDRAGONFLYDOJI", fallback)


@register_indicator(name="gravestone_doji", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["gravestone_doji"])
def gravestone_doji(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        return ((body <= rng * 0.1) & (ls <= rng * 0.1) & (us > rng * 0.5)).astype(int)
    return _auto_select(open_, high, low, close, "CDLGRAVESTONEDOJI", fallback)


@register_indicator(name="harami", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["harami"])
def harami(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        is_bull_harami = bear.shift(1) & bull & (rt < rt.shift(1)) & (rb > rb.shift(1))
        is_bear_harami = bull.shift(1) & bear & (rt < rt.shift(1)) & (rb > rb.shift(1))
        return is_bull_harami.astype(int) - is_bear_harami.astype(int)
    return _auto_select(open_, high, low, close, "CDLHARAMI", fallback)


@register_indicator(name="harami_cross", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["harami_cross"])
def harami_cross(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        is_doji = body <= rng * 0.1
        is_bull_harami = bear.shift(1) & is_doji & (rt < rt.shift(1)) & (rb > rb.shift(1))
        is_bear_harami = bull.shift(1) & is_doji & (rt < rt.shift(1)) & (rb > rb.shift(1))
        return is_bull_harami.astype(int) - is_bear_harami.astype(int)
    return _auto_select(open_, high, low, close, "CDLHARAMICROSS", fallback)


@register_indicator(name="piercing_pattern", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["piercing_pattern"])
def piercing_pattern(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        midpoint_prev = (open_.shift(1) + close.shift(1)) / 2
        return (bear.shift(1) & bull & (open_ < rb.shift(1)) & (close > midpoint_prev) & (close < rt.shift(1))).astype(int)
    return _auto_select(open_, high, low, close, "CDLPIERCING", fallback)


@register_indicator(name="dark_cloud_cover", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["dark_cloud_cover"])
def dark_cloud_cover(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        midpoint_prev = (open_.shift(1) + close.shift(1)) / 2
        return (bull.shift(1) & bear & (open_ > rt.shift(1)) & (close < midpoint_prev) & (close > rb.shift(1))).astype(int) * -1
    return _auto_select(open_, high, low, close, "CDLDARKCLOUDCOVER", fallback)


@register_indicator(name="spinning_top", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["spinning_top"])
def spinning_top(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        is_spinning = (body <= rng * 0.3) & (us > body) & (ls > body)
        return is_spinning.astype(int) * (bull.astype(int) - bear.astype(int))
    return _auto_select(open_, high, low, close, "CDLSPINNINGTOP", fallback)


@register_indicator(name="tweezer_top", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["tweezer_top"])
def tweezer_top(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        is_tweezer = ((high - high.shift(1)).abs() < (high * 0.0001)) & (close < open_)
        return is_tweezer.astype(int) * -1
    return _auto_select(open_, high, low, close, "CDLTWEEZERTOP", fallback)


@register_indicator(name="tweezer_bottom", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["tweezer_bottom"])
def tweezer_bottom(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        is_tweezer = ((low - low.shift(1)).abs() < (low * 0.0001)) & (close > open_)
        return is_tweezer.astype(int)
    return _auto_select(open_, high, low, close, "CDLTWEEZERBOTTOM", fallback)


@register_indicator(name="abandoned_baby", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["abandoned_baby"])
def abandoned_baby(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        is_doji = body.shift(1) <= rng.shift(1) * 0.1
        bull_baby = bear.shift(2) & is_doji & bull & (low.shift(1) < low.shift(2)) & (low.shift(1) < low) & (high.shift(1) < low.shift(2)) & (high.shift(1) < low)
        bear_baby = bull.shift(2) & is_doji & bear & (high.shift(1) > high.shift(2)) & (high.shift(1) > high) & (low.shift(1) > high.shift(2)) & (low.shift(1) > high)
        return bull_baby.astype(int) - bear_baby.astype(int)
    return _auto_select(open_, high, low, close, "CDLABANDONEDBABY", fallback)


def _three_inside_fallback(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
    is_bull_harami = bear.shift(2) & bull.shift(1) & (rt.shift(1) < rt.shift(2)) & (rb.shift(1) > rb.shift(2))
    three_up = is_bull_harami & bull & (close > close.shift(1))
    is_bear_harami = bull.shift(2) & bear.shift(1) & (rt.shift(1) < rt.shift(2)) & (rb.shift(1) > rb.shift(2))
    three_down = is_bear_harami & bear & (close < close.shift(1))
    return three_up.astype(int) - three_down.astype(int)


@register_indicator(name="three_inside_up", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_inside_up"])
def three_inside_up(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    res = _auto_select(open_, high, low, close, "CDL3INSIDE", _three_inside_fallback)
    return (res == 1).astype(int)


@register_indicator(name="three_inside_down", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_inside_down"])
def three_inside_down(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    res = _auto_select(open_, high, low, close, "CDL3INSIDE", _three_inside_fallback)
    return (res == -1).astype(int)


def _three_outside_fallback(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
    is_bull_eng = bear.shift(2) & bull.shift(1) & (body.shift(1) > body.shift(2)) & (rt.shift(1) > rt.shift(2)) & (rb.shift(1) < rb.shift(2))
    three_up = is_bull_eng & bull & (close > close.shift(1))
    is_bear_eng = bull.shift(2) & bear.shift(1) & (body.shift(1) > body.shift(2)) & (rb.shift(1) < rb.shift(2)) & (rt.shift(1) > rt.shift(2))
    three_down = is_bear_eng & bear & (close < close.shift(1))
    return three_up.astype(int) - three_down.astype(int)


@register_indicator(name="three_outside_up", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_outside_up"])
def three_outside_up(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    res = _auto_select(open_, high, low, close, "CDL3OUTSIDE", _three_outside_fallback)
    return (res == 1).astype(int)


@register_indicator(name="three_outside_down", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["three_outside_down"])
def three_outside_down(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    res = _auto_select(open_, high, low, close, "CDL3OUTSIDE", _three_outside_fallback)
    return (res == -1).astype(int)


@register_indicator(name="kicking", category="PATTERN", inputs=["open", "high", "low", "close"], outputs=["kicking"])
def kicking(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    def fallback(open_, high, low, close):
        body, us, ls, rng, bull, bear, rt, rb = get_candle_features(open_, high, low, close)
        is_bull_maru_prev = bear.shift(1) & (us.shift(1) <= rng.shift(1) * 0.05) & (ls.shift(1) <= rng.shift(1) * 0.05)
        is_bull_maru = bull & (us <= rng * 0.05) & (ls <= rng * 0.05)
        bull_kick = is_bull_maru_prev & is_bull_maru & (open_ > open_.shift(1))
        
        is_bear_maru_prev = bull.shift(1) & (us.shift(1) <= rng.shift(1) * 0.05) & (ls.shift(1) <= rng.shift(1) * 0.05)
        is_bear_maru = bear & (us <= rng * 0.05) & (ls <= rng * 0.05)
        bear_kick = is_bear_maru_prev & is_bear_maru & (open_ < open_.shift(1))
        
        return bull_kick.astype(int) - bear_kick.astype(int)
    return _auto_select(open_, high, low, close, "CDLKICKING", fallback)


@register_indicator(
    name="scan_all_candlestick",
    category="PATTERN",
    inputs=["open", "high", "low", "close"],
    outputs=["doji", "engulfing", "hammer", "morning_star", "shooting_star"]
)
def scan_all_candlestick(df: pd.DataFrame) -> pd.DataFrame:
    """Scan for common candlestick patterns."""

    res = pd.DataFrame(index=df.index)
    res['doji'] = doji(df['open'], df['high'], df['low'], df['close'])
    res['engulfing'] = bullish_engulfing(df['open'], df['high'], df['low'], df['close']) - bearish_engulfing(df['open'], df['high'], df['low'], df['close'])
    res['hammer'] = hammer(df['open'], df['high'], df['low'], df['close'])
    res['morning_star'] = morning_star(df['open'], df['high'], df['low'], df['close'])
    res['shooting_star'] = shooting_star(df['open'], df['high'], df['low'], df['close'])
    
    # Adding the rest
    for name in ["hanging_man", "inverted_hammer", "three_white_soldiers", "three_black_crows",
                 "marubozu", "dragonfly_doji", "gravestone_doji", "harami", "harami_cross",
                 "piercing_pattern", "dark_cloud_cover", "spinning_top", "tweezer_top", 
                 "tweezer_bottom", "abandoned_baby", "three_inside_up", "three_inside_down",
                 "three_outside_up", "three_outside_down", "kicking", "evening_star"]:
        func = globals().get(name)
        if func:
            res[name] = func(df['open'], df['high'], df['low'], df['close'])
    
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
