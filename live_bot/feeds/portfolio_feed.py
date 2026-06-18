import logging
import threading
import upstox_client
from typing import Callable, Optional
from live_bot.models import PortfolioUpdate
from live_bot.feeds.adapters.upstox_ws_adapter import UpstoxWebSocketAdapter

logger = logging.getLogger(__name__)

class PortfolioFeed:
    """
    Wraps the Upstox PortfolioDataStreamer WebSocket.
    Delegates parsing to the broker-agnostic adapter.
    """
    def __init__(self, access_token: str, on_portfolio_update: Callable[[PortfolioUpdate], None]):
        self.access_token = access_token
        self.on_portfolio_update = on_portfolio_update
        self._streamer = None
        self._is_connected = False
        self._adapter = UpstoxWebSocketAdapter()
        
    def start(self):
        try:
            config = upstox_client.Configuration()
            config.access_token = self.access_token
            api_client = upstox_client.ApiClient(config)
            
            self._streamer = upstox_client.PortfolioDataStreamer(
                api_client=api_client
            )
            
            self._streamer.on("open", self._on_open)
            self._streamer.on("message", self._on_message)
            self._streamer.on("error", self._on_error)
            self._streamer.on("close", self._on_close)
            
            self._streamer.connect()
            logger.info("PortfolioFeed connect() called")
        except Exception as e:
            logger.error(f"Failed to start PortfolioFeed: {e}")

    def stop(self):
        if self._streamer:
            try:
                self._streamer.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting PortfolioFeed: {e}")
        self._is_connected = False

    def auto_reconnect(self, enable: bool, interval: int = 5, retries: int = 5):
        if self._streamer:
            self._streamer.auto_reconnect(enable, interval, retries)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _on_open(self):
        self._is_connected = True
        logger.info("PortfolioFeed opened")
        
    def _on_message(self, message: dict):
        if not isinstance(message, dict):
            return
            
        update_type = message.get("type", "unknown")
        data = message.get("data", {})
        
        # Structure it for the adapter
        raw_message = {
            "update_type": update_type,
            **data
        }
        
        update = self._adapter.parse_portfolio_message(raw_message)
        if update:
            self.on_portfolio_update(update)
        
    def _on_error(self, error):
        logger.error(f"PortfolioFeed error: {error}")
        
    def _on_close(self):
        self._is_connected = False
        logger.warning("PortfolioFeed closed")
