"""
screener/rules/pattern.py
-------------------------
Pattern recognition rules for the screener.
"""

import pandas as pd

from screener.base import RuleResult, SignalDirection
from screener.rules.base import ScreenRule


class CandlePatternRule(ScreenRule):
    def __init__(self, pattern_name: str, direction: SignalDirection = SignalDirection.BULLISH):
        self.pattern_name = pattern_name
        self.direction = direction
        self.name = f"Candle({pattern_name}) {direction.name}"
        self.description = f"Candlestick pattern: {pattern_name}"
        self.min_bars_required = 10
        self.weight = 1.0
        
        # Verify pattern exists
        from indicators.patterns.candlestick import __all__ as candlestick_patterns
        if pattern_name not in candlestick_patterns and pattern_name != "scan_all_candlestick":
            import logging
            logging.getLogger(__name__).warning(f"Pattern {pattern_name} not found in indicators.patterns.candlestick")

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        import importlib
        try:
            candlestick = importlib.import_module("indicators.patterns.candlestick")
            func = getattr(candlestick, self.pattern_name)
            # candlestick functions take (open, high, low, close)
            res = func(df["open"], df["high"], df["low"], df["close"])
            val = res.iloc[-1]
            
            if self.direction == SignalDirection.BULLISH:
                passed = val == 1
            elif self.direction == SignalDirection.BEARISH:
                passed = val == -1
            elif self.direction == SignalDirection.ANY:
                passed = val != 0
            else:
                passed = False
                
        except Exception as e:
            passed = False
            val = None

        return RuleResult(self.name, bool(passed), float(val) if val is not None else None, None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "CandlePatternRule", "pattern_name": self.pattern_name, "direction": self.direction.name}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        direction_str = data.get("direction", "BULLISH")
        direction = getattr(SignalDirection, direction_str, SignalDirection.BULLISH)
        return cls(pattern_name=data.get("pattern_name", "doji"), direction=direction)


class ChartPatternRule(ScreenRule):
    def __init__(self, pattern_name: str):
        self.pattern_name = pattern_name
        self.name = f"ChartPattern({pattern_name})"
        self.description = f"Chart pattern: {pattern_name}"
        self.min_bars_required = 50
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        import importlib
        try:
            chart_patterns = importlib.import_module("indicators.patterns.chart_patterns")
            func = getattr(chart_patterns, self.pattern_name)
            res = func(df)
            val = res.iloc[-1]
            passed = val == 1
        except Exception as e:
            passed = False
            val = None

        return RuleResult(self.name, bool(passed), float(val) if val is not None else None, None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "ChartPatternRule", "pattern_name": self.pattern_name}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(pattern_name=data.get("pattern_name", "double_bottom"))


class TrendStructureRule(ScreenRule):
    def __init__(self, direction: str = "uptrend", lookback: int = 20):
        self.direction = direction
        self.lookback = lookback
        self.name = f"Trend({direction})"
        self.description = f"Trend structure: {direction}"
        self.min_bars_required = lookback + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        from indicators.patterns.dow_patterns import trend_structure
        ts = trend_structure(df["high"], df["low"])
        val = ts[self.direction].iloc[-1]
        passed = bool(val)
        
        return RuleResult(self.name, passed, 1.0 if passed else 0.0, None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "TrendStructureRule", "direction": self.direction, "lookback": self.lookback}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(direction=data.get("direction", "uptrend"), lookback=data.get("lookback", 20))
