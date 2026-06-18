from dataclasses import dataclass, field
from typing import Any
from live_bot.models import FeedMode

@dataclass
class LiveBotConfig:
    # Strategy
    strategy_class: type
    strategy_params: dict[str, Any] = field(default_factory=dict)

    # Instruments
    instrument_map: dict[str, str] = field(default_factory=dict)
    # {instrument_key: display_symbol}, e.g. {"NSE_EQ|INE020B01018": "RELIANCE"}

    # Feed settings
    feed_mode: FeedMode = FeedMode.FULL
    feed_type: str = "websocket"           # "websocket" | "rest"
    websocket_mode: str = "full"           # validated against FeedMode values
    rest_poll_interval_seconds: float = 1.0
    rest_request_spacing_seconds: float = 0.13
    rest_batch_size: int = 50
    rest_timeout_seconds: float = 10.0
    rest_fallback_enabled: bool = True     # NEW: auto-fallback to REST on WS failure
    rest_fallback_trigger_seconds: float = 30.0  # NEW: WS silent → trigger REST fallback

    # Capital
    initial_capital: float = 500_000.0
    paper_trade: bool = True               # REPLACES global config.PAPER_TRADE

    # Trading params
    product: str = "I"                     # "I"=MIS, "D"=CNC
    daily_loss_limit_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_open_positions: int = 5
    max_position_pct: float = 20.0
    seed_lookback_days: int = 60
    min_bars_required: int = 50
    allow_short: bool = False

    # Staleness
    stale_tick_threshold_seconds: float = 5.0
    start_portfolio_feed: bool = True

    def __post_init__(self):
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid LiveBotConfig: {', '.join(errors)}")

    def validate(self) -> list[str]:
        errors = []
        if not self.instrument_map:
            errors.append("instrument_map cannot be empty")
        if self.initial_capital <= 0:
            errors.append("initial_capital must be > 0")
        if not isinstance(self.feed_mode, FeedMode):
            errors.append(f"feed_mode must be a FeedMode enum, got {type(self.feed_mode)}")
        if self.websocket_mode not in {"ltpc", "full", "option_greeks", "full_d30"}:
            errors.append(f"invalid websocket_mode: {self.websocket_mode}")
        if self.rest_poll_interval_seconds <= 0:
            errors.append("rest_poll_interval_seconds must be > 0")
        return errors

    def to_dict(self) -> dict:
        return {
            "strategy_class": self.strategy_class.__name__ if hasattr(self.strategy_class, "__name__") else str(self.strategy_class),
            "strategy_params": self.strategy_params,
            "instrument_map": self.instrument_map,
            "feed_mode": self.feed_mode.value,
            "feed_type": self.feed_type,
            "websocket_mode": self.websocket_mode,
            "rest_poll_interval_seconds": self.rest_poll_interval_seconds,
            "rest_request_spacing_seconds": self.rest_request_spacing_seconds,
            "rest_batch_size": self.rest_batch_size,
            "rest_timeout_seconds": self.rest_timeout_seconds,
            "rest_fallback_enabled": self.rest_fallback_enabled,
            "rest_fallback_trigger_seconds": self.rest_fallback_trigger_seconds,
            "initial_capital": self.initial_capital,
            "paper_trade": self.paper_trade,
            "product": self.product,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_open_positions": self.max_open_positions,
            "max_position_pct": self.max_position_pct,
            "seed_lookback_days": self.seed_lookback_days,
            "min_bars_required": self.min_bars_required,
            "allow_short": self.allow_short,
            "stale_tick_threshold_seconds": self.stale_tick_threshold_seconds,
            "start_portfolio_feed": self.start_portfolio_feed
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LiveBotConfig':
        kwargs = data.copy()
        
        # Handle feed_mode conversion
        if "feed_mode" in kwargs and isinstance(kwargs["feed_mode"], str):
            kwargs["feed_mode"] = FeedMode(kwargs["feed_mode"])
            
        # strategy_class would be passed independently or resolved
        # This is a basic implementation of from_dict
        if "strategy_class" in kwargs and isinstance(kwargs["strategy_class"], str):
            kwargs["strategy_class"] = type("DummyStrategy", (), {})
            
        return cls(**kwargs)
