"""
backtester/orders.py
--------------------
Single file defining every order type and stop-loss type used in Indian markets.
Pure data + minimal logic. No pandas. No broker imports.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

class OrderType(Enum):
    """Entry execution order types."""
    MARKET      = "MARKET"
    LIMIT       = "LIMIT"
    STOP        = "STOP"
    STOP_LIMIT  = "STOP_LIMIT"
    BRACKET     = "BRACKET"
    COVER       = "COVER"
    AMO         = "AMO"

class StopLossType(Enum):
    """How the stop-loss distance is specified."""
    NONE             = "NONE"
    FIXED_PRICE      = "FIXED_PRICE"
    FIXED_PCT        = "FIXED_PCT"
    FIXED_POINTS     = "FIXED_POINTS"
    FIXED_TICKS      = "FIXED_TICKS"
    ATR_MULTIPLE     = "ATR_MULTIPLE"
    TRAILING_PCT     = "TRAILING_PCT"
    TRAILING_POINTS  = "TRAILING_POINTS"
    TRAILING_ATR     = "TRAILING_ATR"
    TRAILING_TICKS   = "TRAILING_TICKS"
    CHANDELIER       = "CHANDELIER"
    VOLATILITY       = "VOLATILITY"
    SWING_LOW        = "SWING_LOW"
    TIME_BASED       = "TIME_BASED"

    def is_trailing(self) -> bool:
        return self.name.startswith("TRAILING_") or self == StopLossType.CHANDELIER

    def is_fixed(self) -> bool:
        return self.name.startswith("FIXED_")

    def requires_atr(self) -> bool:
        return self in (StopLossType.ATR_MULTIPLE, StopLossType.TRAILING_ATR, StopLossType.CHANDELIER)

class TakeProfitType(Enum):
    """How the take-profit target is specified."""
    NONE            = "NONE"
    FIXED_PRICE     = "FIXED_PRICE"
    FIXED_PCT       = "FIXED_PCT"
    FIXED_POINTS    = "FIXED_POINTS"
    FIXED_TICKS     = "FIXED_TICKS"
    RISK_REWARD     = "RISK_REWARD"
    ATR_MULTIPLE    = "ATR_MULTIPLE"
    PARTIAL_EXIT    = "PARTIAL_EXIT"

    def requires_stop(self) -> bool:
        return self == TakeProfitType.RISK_REWARD

    def is_partial(self) -> bool:
        return self == TakeProfitType.PARTIAL_EXIT

@dataclass(slots=True)
class StopLossSpec:
    """Complete stop-loss specification for one trade."""
    sl_type: StopLossType = StopLossType.NONE
    value: float = 0.0
    tick_size: float = 0.05
    atr_period: int = 14
    chandelier_period: int = 22

    def is_active(self) -> bool:
        return self.sl_type != StopLossType.NONE

    def is_trailing(self) -> bool:
        return self.sl_type.is_trailing()

    def compute_initial_stop(
        self,
        entry_price: float,
        direction: int,
        atr: Optional[float] = None,
        swing_low: Optional[float] = None,
        swing_high: Optional[float] = None,
    ) -> Optional[float]:
        """Compute the initial stop-loss price at trade entry."""
        if self.sl_type in (StopLossType.NONE, StopLossType.TIME_BASED):
            return None
            
        if self.sl_type == StopLossType.FIXED_PRICE:
            return self.value
        elif self.sl_type in (StopLossType.FIXED_PCT, StopLossType.TRAILING_PCT):
            distance = entry_price * (self.value / 100.0)
            return entry_price - (distance * direction)
        elif self.sl_type in (StopLossType.FIXED_POINTS, StopLossType.TRAILING_POINTS):
            return entry_price - (self.value * direction)
        elif self.sl_type in (StopLossType.FIXED_TICKS, StopLossType.TRAILING_TICKS):
            return entry_price - (self.value * self.tick_size * direction)
        elif self.sl_type in (StopLossType.ATR_MULTIPLE, StopLossType.TRAILING_ATR, StopLossType.CHANDELIER):
            if atr is None:
                raise ValueError(f"ATR is required for {self.sl_type}")
            return entry_price - (self.value * atr * direction)
        elif self.sl_type == StopLossType.SWING_LOW:
            if direction == 1:
                if swing_low is None:
                    raise ValueError("swing_low is required for long SWING_LOW stop")
                return swing_low
            else:
                if swing_high is None:
                    raise ValueError("swing_high is required for short SWING_LOW stop")
                return swing_high
        elif self.sl_type == StopLossType.VOLATILITY:
             # Just use ATR field as std dev representation or raise unimplemented for now
             # Actually, models might pass it through 'atr' or a separate parameter.
             # We will just map it simply or raise.
             if atr is None:
                 raise ValueError("Standard deviation (passed as atr) is required for VOLATILITY")
             return entry_price - (self.value * atr * direction)
        
        return None

    def validate(self) -> None:
        """Raise ValueError if spec is inconsistent."""
        if self.sl_type != StopLossType.NONE:
            if self.value <= 0.0 and self.sl_type not in (StopLossType.SWING_LOW, StopLossType.TIME_BASED):
                raise ValueError("value must be > 0 for price-based stops")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        if self.atr_period < 1:
            raise ValueError("atr_period must be >= 1")

@dataclass(slots=True)
class TakeProfitSpec:
    """Complete take-profit specification for one trade."""
    tp_type: TakeProfitType = TakeProfitType.NONE
    value: float = 0.0
    rr_ratio: float = 2.0
    partial_pct: float = 50.0
    tick_size: float = 0.05
    atr_period: int = 14

    def is_active(self) -> bool:
        return self.tp_type != TakeProfitType.NONE

    def compute_target(
        self,
        entry_price: float,
        direction: int,
        sl_distance: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> Optional[float]:
        """Compute the target price at trade entry."""
        if self.tp_type == TakeProfitType.NONE:
            return None
            
        if self.tp_type == TakeProfitType.FIXED_PRICE:
            return self.value
        elif self.tp_type == TakeProfitType.FIXED_PCT:
            distance = entry_price * (self.value / 100.0)
            return entry_price + (distance * direction)
        elif self.tp_type == TakeProfitType.FIXED_POINTS:
            return entry_price + (self.value * direction)
        elif self.tp_type == TakeProfitType.FIXED_TICKS:
            return entry_price + (self.value * self.tick_size * direction)
        elif self.tp_type == TakeProfitType.ATR_MULTIPLE:
            if atr is None:
                raise ValueError("ATR is required for ATR_MULTIPLE take profit")
            return entry_price + (self.value * atr * direction)
        elif self.tp_type == TakeProfitType.RISK_REWARD:
            if sl_distance is None:
                raise ValueError("sl_distance is required for RISK_REWARD take profit")
            return entry_price + (sl_distance * self.rr_ratio * direction)
        elif self.tp_type == TakeProfitType.PARTIAL_EXIT:
            # The value field is used as the initial target distance in points
            return entry_price + (self.value * direction)
            
        return None

    def validate(self, sl_spec: Optional[StopLossSpec] = None) -> None:
        """Raise ValueError if spec inconsistent."""
        if self.tp_type == TakeProfitType.RISK_REWARD:
            if not sl_spec or not sl_spec.is_active():
                raise ValueError("RISK_REWARD target requires an active stop-loss")
        if self.tp_type != TakeProfitType.NONE and self.tp_type not in (TakeProfitType.PARTIAL_EXIT, TakeProfitType.RISK_REWARD):
             if self.value <= 0.0:
                 raise ValueError("value must be > 0 for price-based targets")

@dataclass
class OrderSpec:
    """Complete order specification for one entry signal."""
    direction: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_trigger: Optional[float] = None
    sl_spec: StopLossSpec = field(default_factory=StopLossSpec)
    tp_spec: TakeProfitSpec = field(default_factory=TakeProfitSpec)
    quantity: int = 0
    tag: str = ""
    expires_after: int = 0
    amo: bool = False

    def validate(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError("direction must be 1 or -1")
        self.sl_spec.validate()
        self.tp_spec.validate(self.sl_spec)
        
    def is_bracket(self) -> bool:
        return self.order_type == OrderType.BRACKET
        
    def is_cover(self) -> bool:
        return self.order_type == OrderType.COVER
        
    def has_stop(self) -> bool:
        return self.sl_spec.is_active()
        
    def has_target(self) -> bool:
        return self.tp_spec.is_active()

@dataclass
class PendingOrder:
    """An entry order not yet filled."""
    direction: int
    order_type: OrderType
    quantity: int
    signal_bar: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    expires_after: int = 0
    sl_spec: StopLossSpec = field(default_factory=StopLossSpec)
    tp_spec: TakeProfitSpec = field(default_factory=TakeProfitSpec)
    tag: str = ""
    amo: bool = False
    _stop_triggered: bool = False

@dataclass
class GTTOrder:
    """Good Till Triggered order."""
    direction: int
    trigger_price: float
    limit_price: Optional[float]
    quantity: int
    signal_bar: int
    sl_spec: StopLossSpec = field(default_factory=StopLossSpec)
    tp_spec: TakeProfitSpec = field(default_factory=TakeProfitSpec)
    expiry_bars: int = 0
    tag: str = ""
    triggered: bool = False
    cancelled: bool = False
