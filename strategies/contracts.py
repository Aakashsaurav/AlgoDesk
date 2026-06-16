from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

DEFAULT_SYMBOL = "__symbol__"

class Action(str, Enum):
    """Signal action emitted by a strategy."""
    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    EXIT_ALL = "EXIT_ALL"
    HOLD = "HOLD"

class OrderType(str, Enum):
    """Supported execution order types at strategy level."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"

@dataclass(slots=True)
class Signal:
    """Trading instruction emitted by the strategy."""
    action: Action
    quantity: int = 0
    order_type: str = "MARKET"
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: Optional[float] = None
    tag: str = ""
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class PortfolioState:
    """Read-only portfolio snapshot passed to event-driven strategies."""
    cash: float
    total_value: float
    open_positions: Dict[str, int] = field(default_factory=dict)
    open_position_pnl: Dict[str, float] = field(default_factory=dict)
    current_prices: Dict[str, float] = field(default_factory=dict)
    sector_exposure: Dict[str, float] = field(default_factory=dict)
    peak_value: float = 0.0
    current_drawdown: float = 0.0

    def is_long(self, symbol: str = DEFAULT_SYMBOL) -> bool:
        return self.open_positions.get(symbol, 0) > 0

    def is_short(self, symbol: str = DEFAULT_SYMBOL) -> bool:
        return self.open_positions.get(symbol, 0) < 0

    def is_flat(self, symbol: str = DEFAULT_SYMBOL) -> bool:
        return self.open_positions.get(symbol, 0) == 0

    def position_size(self, symbol: str = DEFAULT_SYMBOL) -> int:
        return self.open_positions.get(symbol, 0)

@dataclass(slots=True)
class StrategyMetadata:
    """Serializable metadata used by registry, UI, and tests."""
    class_name: str
    display_name: str
    description: str
    category: str
    params: Dict[str, Any]
    module_path: str

@dataclass(slots=True)
class ParamSpec:
    """Schema for a strategy parameter."""
    name: str
    type: str
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    label: str = ""
    description: str = ""
    unit: str = ""
    options: Optional[list] = None
    optimize: bool = True
    required: bool = False
    runtime_only: bool = False

class StrategyMode(str, Enum):
    """Execution mode of the strategy."""
    VECTORIZED = "VECTORIZED"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    PORTFOLIO = "PORTFOLIO"

class StrategyScope(str, Enum):
    """Symbol scope of the strategy."""
    SINGLE_SYMBOL = "SINGLE_SYMBOL"
    MULTI_SYMBOL = "MULTI_SYMBOL"
    PORTFOLIO = "PORTFOLIO"
