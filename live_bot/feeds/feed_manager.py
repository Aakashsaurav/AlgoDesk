import threading
import time
import logging
from enum import Enum
from typing import Callable, Optional
from live_bot.config import LiveBotConfig
from live_bot.models import TickData, PortfolioUpdate, FeedMode, FeedSource
from live_bot.feeds.base import FeedAdapterBase

logger = logging.getLogger(__name__)

class FeedState(Enum):
    STARTING     = "STARTING"
    WS_ACTIVE    = "WS_ACTIVE"
    WS_DEGRADED  = "WS_DEGRADED"
    REST_ACTIVE  = "REST_ACTIVE"
    RECONNECTING = "RECONNECTING"
    STOPPED      = "STOPPED"

class FeedManager:
    """
    Manages primary WebSocket feed and REST fallback.
    """
    def __init__(
        self,
        config: LiveBotConfig,
        adapter: FeedAdapterBase,
        access_token: str,
        on_tick: Callable[[TickData], None],
        on_candle_complete: Callable[[str, dict], None],
        on_portfolio_update: Callable[[PortfolioUpdate], None]
    ):
        self.config = config
        self.adapter = adapter
        self.access_token = access_token
        self.on_tick_cb = on_tick
        self.on_candle_complete_cb = on_candle_complete
        self.on_portfolio_update_cb = on_portfolio_update

        self._state = FeedState.STARTING
        self._last_ws_message_at = time.monotonic()
        self._running = False
        
        self._monitor_thread: Optional[threading.Thread] = None
        self._rest_thread: Optional[threading.Thread] = None

        # These will be set by the caller or configured later
        self.ws_feed = None
        self.rest_feed = None

    def start(self):
        self._running = True
        self._state = FeedState.STARTING
        
        if self.ws_feed:
            self.ws_feed.start()
            
        self._monitor_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True)
        self._monitor_thread.start()
        
        if self.config.rest_fallback_enabled:
            self._rest_thread = threading.Thread(target=self._rest_fallback_loop, daemon=True)
            self._rest_thread.start()

    def stop(self):
        self._running = False
        self._state = FeedState.STOPPED
        if self.ws_feed:
            self.ws_feed.stop()

    def _heartbeat_monitor(self):
        while self._running:
            time.sleep(1.0)
            if self._state == FeedState.STOPPED:
                break
                
            elapsed = time.monotonic() - self._last_ws_message_at
            if elapsed > self.config.rest_fallback_trigger_seconds and self._state == FeedState.WS_ACTIVE:
                logger.warning(f"WebSocket silent for {elapsed:.1f}s. Degrading state.")
                self._state = FeedState.WS_DEGRADED
                if self.config.rest_fallback_enabled:
                    logger.warning("Activating REST fallback.")
                    self._state = FeedState.REST_ACTIVE

    def _on_ws_message(self, raw_message: dict):
        self._last_ws_message_at = time.monotonic()
        if self._state in (FeedState.STARTING, FeedState.REST_ACTIVE, FeedState.WS_DEGRADED, FeedState.RECONNECTING):
            self._state = FeedState.WS_ACTIVE
            
        ticks = self.adapter.parse_market_message(raw_message, self.config.instrument_map)
        for tick in ticks:
            self._dispatch_tick(tick)

    def _dispatch_tick(self, tick: TickData):
        self.on_tick_cb(tick)

    def _rest_fallback_loop(self):
        while self._running:
            if self._state != FeedState.REST_ACTIVE:
                time.sleep(1.0)
                continue
                
            if not self.rest_feed:
                time.sleep(1.0)
                continue
                
            try:
                keys = list(self.config.instrument_map.keys())
                ticks = self.rest_feed._fetch_batch(keys)
                for tick in ticks:
                    # Only dispatch if we are still in REST_ACTIVE
                    if self._state == FeedState.REST_ACTIVE:
                        self._dispatch_tick(tick)
            except Exception as e:
                logger.error(f"REST fallback error: {e}")
                
            time.sleep(self.config.rest_poll_interval_seconds)

    def subscribe(self, instrument_keys: list[str], mode: FeedMode):
        if self.ws_feed:
            self.ws_feed.subscribe(instrument_keys, mode)

    def unsubscribe(self, instrument_keys: list[str]):
        if self.ws_feed:
            self.ws_feed.unsubscribe(instrument_keys)

    def change_mode(self, instrument_keys: list[str], mode: FeedMode):
        if self.ws_feed:
            self.ws_feed.change_mode(instrument_keys, mode)

    def get_state(self) -> FeedState:
        return self._state

    def get_stats(self) -> dict:
        return {
            "state": self._state.value,
            "last_ws_message_seconds_ago": time.monotonic() - self._last_ws_message_at
        }
