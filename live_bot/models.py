from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from backtester.orders import StopLossSpec, TakeProfitSpec
import pytz

IST_TZ = pytz.timezone("Asia/Kolkata")

class FeedMode(str, Enum):
    LTPC          = "ltpc"          # LTP + close price only
    FULL          = "full"          # LTPC + D5 depth + OHLC candles
    OPTION_GREEKS = "option_greeks" # LTPC + greeks
    FULL_D30      = "full_d30"      # Full + 30-level depth

class FeedSource(str, Enum):
    WEBSOCKET = "websocket"   # Primary: live WebSocket
    REST      = "rest"        # Fallback: REST polling
    SEED      = "seed"        # Historical seed data

@dataclass(slots=True)
class LTPCData:
    ltp: float            # Last traded price
    ltt: datetime         # Last trade time (IST)
    ltq: int              # Last traded quantity
    close_price: float    # Previous day close

@dataclass(slots=True)
class MarketDepthLevel:
    bid_price: float
    bid_qty: int
    bid_orders: int
    ask_price: float
    ask_qty: int
    ask_orders: int

@dataclass(slots=True)
class OHLCCandle:
    interval: str         # "1d", "I1", "I30"
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime

@dataclass(slots=True)
class OptionGreeks:
    option_price: float
    underlying_price: float
    implied_volatility: float
    delta: float
    theta: float
    gamma: float
    vega: float
    rho: float

@dataclass
class TickData:
    # Identity
    instrument_key: str
    symbol: str
    feed_mode: FeedMode
    feed_source: FeedSource
    received_at: datetime

    # LTPC (present in all modes)
    ltpc: LTPCData

    # Full mode extras (None in LTPC mode)
    depth_5: Optional[list[MarketDepthLevel]] = None    # 5-level bid/ask
    depth_30: Optional[list[MarketDepthLevel]] = None   # 30-level (full_d30 only)
    ohlc_candles: Optional[list[OHLCCandle]] = None     # 1min, 30min, daily
    yearly_high: Optional[float] = None
    yearly_low: Optional[float] = None
    volume: Optional[int] = None
    atp: Optional[float] = None                          # Average trade price
    total_buy_qty: Optional[int] = None
    total_sell_qty: Optional[int] = None
    lower_circuit: Optional[float] = None
    upper_circuit: Optional[float] = None
    oi: Optional[float] = None

    # Option greeks (None for non-options)
    greeks: Optional[OptionGreeks] = None

    @property
    def ltp(self) -> float:
        return self.ltpc.ltp

    @property
    def ltt(self) -> datetime:
        return self.ltpc.ltt

    def get_1min_candle(self) -> Optional[OHLCCandle]:
        """Returns the current 1-minute candle from feed, if available."""
        if not self.ohlc_candles:
            return None
        return next((c for c in self.ohlc_candles if c.interval == "I1"), None)

    def is_stale(self, max_age_seconds: float = 5.0) -> bool:
        now = datetime.now(tz=IST_TZ)
        if self.received_at.tzinfo is None:
            received_at = IST_TZ.localize(self.received_at)
        else:
            received_at = self.received_at
            
        delta = (now - received_at).total_seconds()
        return delta > max_age_seconds

    def validate(self) -> bool:
        return self.ltpc.ltp > 0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialisation."""
        return {
            "instrument_key": self.instrument_key,
            "symbol": self.symbol,
            "feed_mode": self.feed_mode.value,
            "feed_source": self.feed_source.value,
            "received_at": self.received_at.isoformat(),
            "ltp": self.ltp,
            "ltt": self.ltt.isoformat(),
            "ltq": self.ltpc.ltq,
            "close_price": self.ltpc.close_price
        }

@dataclass
class LivePosition:
    """Represents an open paper-trade position."""
    symbol:          str
    instrument_key:  str
    direction:       int             # 1 for LONG, -1 for SHORT
    quantity:        int
    entry_price:     float
    entry_time:      datetime
    stop_loss:       Optional[float] = None
    take_profit:     Optional[float] = None
    entry_commission: float = 0.0
    strategy_tag: str = ""
    sl_spec:         Optional[StopLossSpec] = None
    tp_spec:         Optional[TakeProfitSpec] = None

@dataclass
class LiveOrder:
    """State of a paper-trade order."""
    order_id:        str
    symbol:          str
    instrument_key:  str
    action:          str          # "BUY" or "SELL"
    quantity:        int
    order_type:      str          # "MARKET" or "LIMIT"
    limit_price:     Optional[float]
    status:          str          # "PENDING", "FILLED", "CANCELLED", "REJECTED"
    created_at:      datetime
    filled_at:       Optional[datetime] = None
    fill_price:      Optional[float] = None
    strategy_tag:    str = ""
    pnl:             float = 0.0  # Only set when closing a position

@dataclass
class ClosedTrade:
    """A completed round-trip trade (entry + exit)."""
    symbol:          str
    direction:       str
    quantity:        int
    entry_price:     float
    exit_price:      float
    entry_time:      datetime
    exit_time:       datetime
    pnl:             float
    pnl_pct:         float
    strategy_tag:    str = ""
    exit_reason:     str = ""     # "SIGNAL", "STOP_LOSS", "TAKE_PROFIT", "SQUAREOFF", "KILL_SWITCH"
    entry_commission: float = 0.0
    exit_commission: float = 0.0
    sl_type:         str = ""
    tp_type:         str = ""

@dataclass(slots=True)
class PortfolioUpdate:
    update_type: str       # "order_update" | "position_update" | "holding_update" | "gtt_update"
    order_id: Optional[str]
    status: Optional[str]
    instrument_key: Optional[str]
    transaction_type: Optional[str]
    quantity: int
    average_price: float
    filled_quantity: int
    raw: dict              # original payload preserved
    received_at: datetime

@dataclass
class SessionStats:
    session_date: str
    symbols_subscribed: list[str]
    feed_mode: FeedMode
    ticks_received: int
    candles_completed: int
    orders_placed: int
    websocket_disconnects: int
    rest_fallback_activations: int
    started_at: datetime
    ended_at: Optional[datetime] = None
