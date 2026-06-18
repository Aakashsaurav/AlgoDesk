import logging
import upstox_client
from live_bot.models import FeedMode
from live_bot.feeds.feed_manager import FeedManager

logger = logging.getLogger(__name__)

class WebSocketFeed:
    def __init__(self, access_token: str, feed_manager: FeedManager):
        self.access_token = access_token
        self.feed_manager = feed_manager
        self._streamer = None
        self._is_connected = False
        
    def start(self):
        try:
            # We initialize MarketDataStreamerV3 according to upstox API
            self._streamer = upstox_client.MarketDataStreamerV3(
                access_token=self.access_token,
                api_client=upstox_client.ApiClient()
            )
            
            # Map callbacks
            self._streamer.on("open", self._on_open)
            self._streamer.on("message", self._on_message)
            self._streamer.on("error", self._on_error)
            self._streamer.on("close", self._on_close)
            self._streamer.on("reconnecting", self._on_reconnecting)
            self._streamer.on("autoReconnectStopped", self._on_reconnect_stopped)
            
            self._streamer.connect()
            logger.info("WebSocketFeed connect() called")
        except Exception as e:
            logger.error(f"Failed to start WebSocketFeed: {e}")

    def stop(self):
        if self._streamer:
            try:
                self._streamer.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting WebSocketFeed: {e}")
        self._is_connected = False

    def subscribe(self, keys: list[str], mode: FeedMode):
        if self._streamer and self._is_connected:
            self._streamer.subscribe(keys, mode.value)
            
    def unsubscribe(self, keys: list[str]):
        if self._streamer and self._is_connected:
            self._streamer.unsubscribe(keys)
            
    def change_mode(self, keys: list[str], mode: FeedMode):
        if self._streamer and self._is_connected:
            self._streamer.change_mode(keys, mode.value)

    def auto_reconnect(self, enable: bool, interval: int = 5, retries: int = 5):
        if self._streamer:
            self._streamer.auto_reconnect(enable, interval, retries)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _on_open(self):
        self._is_connected = True
        logger.info("WebSocketFeed opened")
        # In a real setup, we'd trigger feed_manager state updates and resubscribe
        
    def _on_message(self, message):
        self.feed_manager._on_ws_message(message)
        
    def _on_error(self, error):
        logger.error(f"WebSocketFeed error: {error}")
        
    def _on_close(self):
        self._is_connected = False
        logger.warning("WebSocketFeed closed")
        
    def _on_reconnecting(self, message):
        logger.warning(f"WebSocketFeed reconnecting: {message}")
        
    def _on_reconnect_stopped(self, message):
        logger.error(f"WebSocketFeed autoReconnectStopped: {message}")
        self._is_connected = False
        # FeedManager's heartbeat monitor will handle activating the kill switch or REST fallback.
