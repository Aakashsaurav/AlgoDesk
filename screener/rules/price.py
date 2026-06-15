"""
screener/rules/price.py
-----------------------
Price Action Rules for the screener.
"""

import pandas as pd

from screener.base import RuleResult
from screener.rules.base import ScreenRule


class PriceBreakoutRule(ScreenRule):
    def __init__(self, lookback: int = 20, direction: str = "above"):
        self.lookback = lookback
        self.direction = direction
        self.name = f"Breakout({lookback}) {direction}"
        self.description = f"Price breaks {lookback}-bar high/low"
        self.min_bars_required = lookback + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        
        if self.direction == "above":
            # high over previous N bars (not including current)
            n_high = df["high"].iloc[-self.lookback-1:-1].max()
            passed = prev_close <= n_high and close > n_high
            threshold = float(n_high)
        elif self.direction == "below":
            n_low = df["low"].iloc[-self.lookback-1:-1].min()
            passed = prev_close >= n_low and close < n_low
            threshold = float(n_low)
        else:
            passed = False
            threshold = None

        return RuleResult(self.name, bool(passed), float(close), threshold, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "PriceBreakoutRule", "lookback": self.lookback, "direction": self.direction}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(lookback=data.get("lookback", 20), direction=data.get("direction", "above"))


class NearSupportRule(ScreenRule):
    def __init__(self, sr_levels: list = None, tolerance_pct: float = 0.02):
        self.sr_levels = sr_levels or []
        self.tolerance_pct = tolerance_pct
        self.name = f"NearSupport({tolerance_pct*100}%)"
        self.description = "Price within tolerance of a support level"
        self.min_bars_required = 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        close = df["close"].iloc[-1]
        passed = False
        nearest = None

        if self.sr_levels:
            supports = [l for l in self.sr_levels if l.price <= close * (1 + self.tolerance_pct)]
            if supports:
                nearest = max(supports, key=lambda x: x.price)
                if close <= nearest.price * (1 + self.tolerance_pct) and close >= nearest.price * (1 - self.tolerance_pct):
                    passed = True
                else:
                    passed = False

        return RuleResult(self.name, bool(passed), float(close), float(nearest.price) if nearest else None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "NearSupportRule", "tolerance_pct": self.tolerance_pct}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(sr_levels=[], tolerance_pct=data.get("tolerance_pct", 0.02))


class NearResistanceRule(ScreenRule):
    def __init__(self, sr_levels: list = None, tolerance_pct: float = 0.02):
        self.sr_levels = sr_levels or []
        self.tolerance_pct = tolerance_pct
        self.name = f"NearResistance({tolerance_pct*100}%)"
        self.description = "Price within tolerance of a resistance level"
        self.min_bars_required = 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        close = df["close"].iloc[-1]
        passed = False
        nearest = None

        if self.sr_levels:
            resistances = [l for l in self.sr_levels if l.price >= close * (1 - self.tolerance_pct)]
            if resistances:
                nearest = min(resistances, key=lambda x: x.price)
                if close >= nearest.price * (1 - self.tolerance_pct) and close <= nearest.price * (1 + self.tolerance_pct):
                    passed = True
                else:
                    passed = False

        return RuleResult(self.name, bool(passed), float(close), float(nearest.price) if nearest else None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "NearResistanceRule", "tolerance_pct": self.tolerance_pct}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(sr_levels=[], tolerance_pct=data.get("tolerance_pct", 0.02))


class PriceRangeRule(ScreenRule):
    def __init__(self, min_price: float = 0.0, max_price: float = 0.0):
        self.min_price = min_price
        self.max_price = max_price
        self.name = f"PriceRange({min_price}-{max_price})"
        self.description = "Price band filter"
        self.min_bars_required = 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        close = df["close"].iloc[-1]
        passed = True
        if self.min_price > 0 and close < self.min_price:
            passed = False
        if self.max_price > 0 and close > self.max_price:
            passed = False
        return RuleResult(self.name, bool(passed), float(close), None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "PriceRangeRule", "min_price": self.min_price, "max_price": self.max_price}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(min_price=data.get("min_price", 0.0), max_price=data.get("max_price", 0.0))


class HigherHighRule(ScreenRule):
    def __init__(self, lookback: int = 20, order: int = 5):
        self.lookback = lookback
        self.order = order
        self.name = f"HigherHigh({lookback},{order})"
        self.description = "Price making higher highs"
        self.min_bars_required = lookback + order * 2 + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        from indicators.patterns.dow_patterns import find_swings
        # Get recent swings
        swings = find_swings(df["high"], df["low"], window=self.order)
        swing_highs = swings[swings["swing_high"]]["swing_high_price"].dropna()
        
        if len(swing_highs) >= 2:
            last_high = swing_highs.iloc[-1]
            prev_high = swing_highs.iloc[-2]
            passed = last_high > prev_high
        else:
            passed = False
            last_high = None

        return RuleResult(self.name, bool(passed), float(last_high) if last_high else None, None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "HigherHighRule", "lookback": self.lookback, "order": self.order}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(lookback=data.get("lookback", 20), order=data.get("order", 5))


class LowerLowRule(ScreenRule):
    def __init__(self, lookback: int = 20, order: int = 5):
        self.lookback = lookback
        self.order = order
        self.name = f"LowerLow({lookback},{order})"
        self.description = "Price making lower lows"
        self.min_bars_required = lookback + order * 2 + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        from indicators.patterns.dow_patterns import find_swings
        swings = find_swings(df["high"], df["low"], window=self.order)
        swing_lows = swings[swings["swing_low"]]["swing_low_price"].dropna()
        
        if len(swing_lows) >= 2:
            last_low = swing_lows.iloc[-1]
            prev_low = swing_lows.iloc[-2]
            passed = last_low < prev_low
        else:
            passed = False
            last_low = None

        return RuleResult(self.name, passed, float(last_low) if last_low else None, None, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "LowerLowRule", "lookback": self.lookback, "order": self.order}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(lookback=data.get("lookback", 20), order=data.get("order", 5))
