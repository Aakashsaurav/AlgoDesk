"""
screener/rules/technical.py
---------------------------
Technical indicator rules for the screener.
"""

import pandas as pd

from screener.base import RuleResult
from screener.rules.base import ScreenRule
from indicators.engine import IndicatorEngine

# Shared indicator engine for all rules
_engine = IndicatorEngine()


class RSIRule(ScreenRule):
    def __init__(self, period: int = 14, threshold: float = 30.0, direction: str = "below"):
        self.period = period
        self.threshold = threshold
        self.direction = direction
        self.name = f"RSI({period}) {direction} {threshold}"
        self.description = "Relative Strength Index filter"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        rsi_series = _engine.compute("rsi", df["close"], period=self.period)
        val = rsi_series.iloc[-1]
        prev_val = rsi_series.iloc[-2] if len(rsi_series) > 1 else val

        if self.direction == "below":
            passed = val < self.threshold
        elif self.direction == "above":
            passed = val > self.threshold
        elif self.direction == "cross_above":
            passed = prev_val <= self.threshold and val > self.threshold
        elif self.direction == "cross_below":
            passed = prev_val >= self.threshold and val < self.threshold
        else:
            passed = False

        return RuleResult(self.name, bool(passed), float(val), self.threshold, {"prev_value": float(prev_val)}, self.weight)

    def to_dict(self) -> dict:
        return {
            "type": "RSIRule",
            "period": self.period,
            "threshold": self.threshold,
            "direction": self.direction
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 14), threshold=data.get("threshold", 30.0), direction=data.get("direction", "below"))


class MACDRule(ScreenRule):
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, condition: str = "cross_above"):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.condition = condition
        self.name = f"MACD({fast},{slow},{signal}) {condition}"
        self.description = "MACD filter"
        self.min_bars_required = slow + signal
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        # Assuming MACD returns DataFrame with 'macd', 'signal', 'histogram'
        macd_df = _engine.compute("macd", df["close"], fast_period=self.fast, slow_period=self.slow, signal_period=self.signal)
        macd = macd_df["macd"].iloc[-1]
        sig = macd_df["signal"].iloc[-1]
        hist = macd_df["histogram"].iloc[-1]

        prev_macd = macd_df["macd"].iloc[-2] if len(macd_df) > 1 else macd
        prev_sig = macd_df["signal"].iloc[-2] if len(macd_df) > 1 else sig

        if self.condition == "cross_above":
            passed = prev_macd <= prev_sig and macd > sig
        elif self.condition == "cross_below":
            passed = prev_macd >= prev_sig and macd < sig
        elif self.condition == "histogram_positive":
            passed = hist > 0
        elif self.condition == "histogram_negative":
            passed = hist < 0
        else:
            passed = False

        return RuleResult(self.name, bool(passed), float(macd), float(sig), {"histogram": float(hist)}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "MACDRule", "fast": self.fast, "slow": self.slow, "signal": self.signal, "condition": self.condition}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(fast=data.get("fast", 12), slow=data.get("slow", 26), signal=data.get("signal", 9), condition=data.get("condition", "cross_above"))


class EMARule(ScreenRule):
    def __init__(self, period: int = 20, condition: str = "price_above"):
        self.period = period
        self.condition = condition
        self.name = f"EMA({period}) {condition}"
        self.description = "Exponential Moving Average filter"
        self.min_bars_required = period
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        ema_series = _engine.compute("ema", df["close"], period=self.period)
        val = ema_series.iloc[-1]
        close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2] if len(df) > 1 else close
        prev_val = ema_series.iloc[-2] if len(ema_series) > 1 else val

        if self.condition == "price_above":
            passed = close > val
        elif self.condition == "price_below":
            passed = close < val
        elif self.condition == "cross_above":
            passed = prev_close <= prev_val and close > val
        elif self.condition == "cross_below":
            passed = prev_close >= prev_val and close < val
        else:
            passed = False

        return RuleResult(self.name, bool(passed), float(val), float(close), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "EMARule", "period": self.period, "condition": self.condition}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 20), condition=data.get("condition", "price_above"))


class GoldenCrossRule(ScreenRule):
    def __init__(self, fast: int = 50, slow: int = 200):
        self.fast = fast
        self.slow = slow
        self.name = f"GoldenCross({fast},{slow})"
        self.description = "Golden Cross (Fast EMA crosses above Slow EMA)"
        self.min_bars_required = slow + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        fast_ema = _engine.compute("ema", df["close"], period=self.fast)
        slow_ema = _engine.compute("ema", df["close"], period=self.slow)
        
        val_f = fast_ema.iloc[-1]
        val_s = slow_ema.iloc[-1]
        prev_f = fast_ema.iloc[-2] if len(fast_ema) > 1 else val_f
        prev_s = slow_ema.iloc[-2] if len(slow_ema) > 1 else val_s

        passed = prev_f <= prev_s and val_f > val_s
        return RuleResult(self.name, bool(passed), float(val_f), float(val_s), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "GoldenCrossRule", "fast": self.fast, "slow": self.slow}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(fast=data.get("fast", 50), slow=data.get("slow", 200))


class DeathCrossRule(ScreenRule):
    def __init__(self, fast: int = 50, slow: int = 200):
        self.fast = fast
        self.slow = slow
        self.name = f"DeathCross({fast},{slow})"
        self.description = "Death Cross (Fast EMA crosses below Slow EMA)"
        self.min_bars_required = slow + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        fast_ema = _engine.compute("ema", df["close"], period=self.fast)
        slow_ema = _engine.compute("ema", df["close"], period=self.slow)
        
        val_f = fast_ema.iloc[-1]
        val_s = slow_ema.iloc[-1]
        prev_f = fast_ema.iloc[-2] if len(fast_ema) > 1 else val_f
        prev_s = slow_ema.iloc[-2] if len(slow_ema) > 1 else val_s

        passed = prev_f >= prev_s and val_f < val_s
        return RuleResult(self.name, bool(passed), float(val_f), float(val_s), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "DeathCrossRule", "fast": self.fast, "slow": self.slow}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(fast=data.get("fast", 50), slow=data.get("slow", 200))


class SupertrendRule(ScreenRule):
    def __init__(self, period: int = 10, multiplier: float = 3.0, direction: str = "bullish"):
        self.period = period
        self.multiplier = multiplier
        self.direction = direction
        self.name = f"Supertrend({period},{multiplier}) {direction}"
        self.description = "Supertrend filter"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        st_df = _engine.compute("supertrend", df["high"], df["low"], df["close"], period=self.period, multiplier=self.multiplier)
        val = st_df["supertrend"].iloc[-1]
        dir_val = st_df["direction"].iloc[-1]
        prev_dir_val = st_df["direction"].iloc[-2] if len(st_df) > 1 else dir_val

        if self.direction == "bullish":
            passed = dir_val == 1
        elif self.direction == "bearish":
            passed = dir_val == -1
        elif self.direction == "flip_bullish":
            passed = prev_dir_val == -1 and dir_val == 1
        elif self.direction == "flip_bearish":
            passed = prev_dir_val == 1 and dir_val == -1
        else:
            passed = False

        return RuleResult(self.name, bool(passed), float(val), None, {"direction": int(dir_val)}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "SupertrendRule", "period": self.period, "multiplier": self.multiplier, "direction": self.direction}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 10), multiplier=data.get("multiplier", 3.0), direction=data.get("direction", "bullish"))


class BollingerSqueezeRule(ScreenRule):
    def __init__(self, bb_period: int = 20, bb_std: float = 2.0, kc_period: int = 20, kc_mult: float = 1.5):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.kc_period = kc_period
        self.kc_mult = kc_mult
        self.name = f"BBSqueeze({bb_period},{bb_std},{kc_period},{kc_mult})"
        self.description = "Bollinger Bands inside Keltner Channels"
        self.min_bars_required = max(bb_period, kc_period) + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        bb = _engine.compute("bollinger_bands", df["close"], period=self.bb_period, std_dev=self.bb_std)
        # Assuming kc function exists. If not, we might need a fallback or calculate it here.
        try:
            kc = _engine.compute("keltner_channels", df, period=self.kc_period, multiplier=self.kc_mult)
            bb_up, bb_dn = bb["upper"].iloc[-1], bb["lower"].iloc[-1]
            kc_up, kc_dn = kc["upper"].iloc[-1], kc["lower"].iloc[-1]
            passed = (bb_up <= kc_up) and (bb_dn >= kc_dn)
        except Exception:
            # Fallback if keltner not available
            passed = False
            bb_up, kc_up = 0.0, 0.0

        return RuleResult(self.name, bool(passed), float(bb_up), float(kc_up), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "BollingerSqueezeRule", "bb_period": self.bb_period, "bb_std": self.bb_std, "kc_period": self.kc_period, "kc_mult": self.kc_mult}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(bb_period=data.get("bb_period", 20), bb_std=data.get("bb_std", 2.0), kc_period=data.get("kc_period", 20), kc_mult=data.get("kc_mult", 1.5))


class RelativeStrengthRule(ScreenRule):
    def __init__(self, benchmark_df: pd.DataFrame, period: int = 55, threshold: float = 0.0, condition: str = "above"):
        self.benchmark_df = benchmark_df
        self.period = period
        self.threshold = threshold
        self.condition = condition
        self.name = f"RS({period}) {condition} {threshold}"
        self.description = "Mansfield Relative Strength"
        self.min_bars_required = period + 1
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        if self.benchmark_df is None or self.benchmark_df.empty:
            return RuleResult(self.name, False, None, None, {"error": "Missing benchmark_df"}, self.weight)

        # align dates
        aligned = pd.merge(df["close"].rename("stock"), self.benchmark_df["close"].rename("bench"), left_index=True, right_index=True, how="inner")
        if len(aligned) < self.min_bars_required:
            return RuleResult(self.name, False, None, None, {"error": "Not enough aligned bars"}, self.weight)

        ratio = aligned["stock"] / aligned["bench"]
        ratio_sma = ratio.rolling(self.period).mean()
        rs = ((ratio / ratio_sma) - 1) * 100
        
        val = rs.iloc[-1]
        prev_val = rs.iloc[-2] if len(rs) > 1 else val

        if self.condition == "above":
            passed = val > self.threshold
        elif self.condition == "below":
            passed = val < self.threshold
        elif self.condition == "improving":
            passed = val > prev_val
        else:
            passed = False

        return RuleResult(self.name, passed, float(val), self.threshold, {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "RelativeStrengthRule", "period": self.period, "threshold": self.threshold, "condition": self.condition}
        # benchmark_df cannot be serialized directly easily, must be re-injected on load

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        # Note: benchmark_df must be set post-deserialization by the caller
        return cls(benchmark_df=pd.DataFrame(), period=data.get("period", 55), threshold=data.get("threshold", 0.0), condition=data.get("condition", "above"))


class ADXRule(ScreenRule):
    def __init__(self, period: int = 14, threshold: float = 25.0, condition: str = "above"):
        self.period = period
        self.threshold = threshold
        self.condition = condition
        self.name = f"ADX({period}) {condition} {threshold}"
        self.description = "Average Directional Index"
        self.min_bars_required = period * 2
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        adx_df = _engine.compute("adx", df["high"], df["low"], df["close"], period=self.period)
        val = adx_df["adx"].iloc[-1]
        plus_di = adx_df["plus_di"].iloc[-1]
        minus_di = adx_df["minus_di"].iloc[-1]

        if self.condition == "above":
            passed = val > self.threshold
        elif self.condition == "di_plus_above":
            passed = val > self.threshold and plus_di > minus_di
        elif self.condition == "di_minus_above":
            passed = val > self.threshold and minus_di > plus_di
        else:
            passed = False

        return RuleResult(self.name, passed, float(val), self.threshold, {"plus_di": float(plus_di), "minus_di": float(minus_di)}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "ADXRule", "period": self.period, "threshold": self.threshold, "condition": self.condition}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(period=data.get("period", 14), threshold=data.get("threshold", 25.0), condition=data.get("condition", "above"))


class VWAPRule(ScreenRule):
    def __init__(self, condition: str = "price_above"):
        self.condition = condition
        self.name = f"VWAP {condition}"
        self.description = "Volume Weighted Average Price"
        self.min_bars_required = 2
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        # Check if intraday by index
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            return RuleResult(self.name, False, None, None, {"error": "VWAP requires datetime index"}, self.weight)
        
        if len(df) > 1:
            time_diff = df.index.to_series().diff().median()
            if time_diff >= pd.Timedelta(days=1):
                import logging
                logging.getLogger(__name__).warning(
                    "VWAPRule used on daily data: VWAP will reset each day, treating each day as a separate session."
                )
        
        # Calculate session VWAP
        v = df['volume']
        tp = (df['high'] + df['low'] + df['close']) / 3
        vwap = (tp * v).groupby(df.index.date).cumsum() / v.groupby(df.index.date).cumsum()
        
        val = vwap.iloc[-1]
        close = df["close"].iloc[-1]
        prev_val = vwap.iloc[-2] if len(vwap) > 1 else val
        prev_close = df["close"].iloc[-2] if len(df) > 1 else close

        if self.condition == "price_above":
            passed = close > val
        elif self.condition == "price_below":
            passed = close < val
        elif self.condition == "cross_above":
            passed = prev_close <= prev_val and close > val
        elif self.condition == "cross_below":
            passed = prev_close >= prev_val and close < val
        else:
            passed = False

        return RuleResult(self.name, passed, float(val), float(close), {}, self.weight)

    def to_dict(self) -> dict:
        return {"type": "VWAPRule", "condition": self.condition}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        return cls(condition=data.get("condition", "price_above"))
