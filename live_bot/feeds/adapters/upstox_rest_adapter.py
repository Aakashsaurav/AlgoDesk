import logging
from live_bot.models import TickData
from live_bot.feeds.adapters.upstox_ws_adapter import UpstoxWebSocketAdapter
from config import config

logger = logging.getLogger(__name__)

class UpstoxRestAdapter:
    def __init__(self):
        self._ws_adapter = UpstoxWebSocketAdapter()

    def build_ltp_request(self, instrument_keys: list[str]) -> dict:
        return {"instrument_key": ",".join(instrument_keys)}

    def build_quote_request(self, instrument_keys: list[str]) -> dict:
        return {"instrument_key": ",".join(instrument_keys)}

    def parse_ltp_response(self, response: dict, instrument_map: dict[str, str]) -> list[TickData]:
        return self._ws_adapter.parse_rest_quote(response, instrument_map)

    def parse_quote_response(self, response: dict, instrument_map: dict[str, str]) -> list[TickData]:
        return self._ws_adapter.parse_rest_quote(response, instrument_map)

    def get_ltp_url(self) -> str:
        return f"{config.UPSTOX_BASE_URL}/v3/market-quote/ltp"

    def get_quote_url(self) -> str:
        return f"{config.UPSTOX_BASE_URL}/v3/market-quote/quotes"
