"""
screener/rules/volume.py
------------------------
Volume Rules for the screener.
"""

import pandas as pd

from screener.base import RuleResult
from screener.rules.base import ScreenRule
from indicators.engine import IndicatorEngine

_engine = IndicatorEngine()


class VolumeBreakoutRule(ScreenRule):
    def __init__(self, period: int = 20, multiplier: float = 2.0):
        self.period = period
        self.multiplier = multiplier
        self.name = f"VolBreakout({period},{multiplier})"
        self.description = "Volume > multiplier * average volume"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].iloc[-self.period-1:-1].mean()
        
        passed = vol > avg_vol * self.multiplier
        return RuleResult(self.name, bool(passed), float(vol), float(avg_vol * self.multiplier), {"avg_vol": float(avg_vol)}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "VolumeBreakoutRule", "period": self.period, "multiplier": self.multiplier}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 20), multiplier=data.get("multiplier", 2.0))


class VolumeDeclineRule(ScreenRule):
    def __init__(self, period: int = 20, multiplier: float = 0.5):
        self.period = period
        self.multiplier = multiplier
        self.name = f"VolDecline({period},{multiplier})"
        self.description = "Volume < multiplier * average volume (drying up)"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].iloc[-self.period-1:-1].mean()
        
        passed = vol < avg_vol * self.multiplier
        return RuleResult(self.name, bool(passed), float(vol), float(avg_vol * self.multiplier), {"avg_vol": float(avg_vol)}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "VolumeDeclineRule", "period": self.period, "multiplier": self.multiplier}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 20), multiplier=data.get("multiplier", 0.5))


class VolumeRatioRule(ScreenRule):
    def __init__(self, period: int = 20, threshold: float = 1.5):
        self.period = period
        self.threshold = threshold
        self.name = f"VolRatio({period})>{threshold}"
        self.description = "Ratio of today's volume to average volume"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].iloc[-self.period-1:-1].mean()
        ratio = vol / avg_vol if avg_vol > 0 else 0.0
        
        passed = ratio > self.threshold
        return RuleResult(self.name, bool(passed), float(ratio), self.threshold, {"avg_vol": float(avg_vol)}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "VolumeRatioRule", "period": self.period, "threshold": self.threshold}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 20), threshold=data.get("threshold", 1.5))


class AccumulationRule(ScreenRule):
    def __init__(self, period: int = 10):
        self.period = period
        self.name = f"Accumulation({period})"
        self.description = "Price up + volume up = accumulation signal"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        obv = _engine.compute("obv", df["close"], df["volume"])
        obv_val = obv.iloc[-1]
        obv_ma = obv.rolling(self.period).mean().iloc[-1]
        
        passed = obv_val > obv_ma
        return RuleResult(self.name, bool(passed), float(obv_val), float(obv_ma), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "AccumulationRule", "period": self.period}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 10))


class DistributionRule(ScreenRule):
    def __init__(self, period: int = 10):
        self.period = period
        self.name = f"Distribution({period})"
        self.description = "Price down + volume up = distribution signal"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        obv = _engine.compute("obv", df["close"], df["volume"])
        obv_val = obv.iloc[-1]
        obv_ma = obv.rolling(self.period).mean().iloc[-1]
        
        passed = obv_val < obv_ma
        return RuleResult(self.name, passed, float(obv_val), float(obv_ma), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "DistributionRule", "period": self.period}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 10))
