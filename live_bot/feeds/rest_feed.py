import time
import requests
import logging
from typing import List
from live_bot.config import LiveBotConfig
from live_bot.models import TickData
from live_bot.feeds.adapters.upstox_rest_adapter import UpstoxRestAdapter

logger = logging.getLogger(__name__)

class RestFeed:
    def __init__(self, config: LiveBotConfig, access_token: str, adapter: UpstoxRestAdapter):
        self.config = config
        self.access_token = access_token
        self.adapter = adapter
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}"
        })
        self._last_request_time = 0.0

    def _sleep_for_rate_limit(self):
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.config.rest_request_spacing_seconds:
            time.sleep(self.config.rest_request_spacing_seconds - elapsed)
        self._last_request_time = time.monotonic()

    def _chunked(self, items: list, n: int):
        for i in range(0, len(items), n):
            yield items[i:i + n]

    def _fetch_batch(self, keys: list[str]) -> list[TickData]:
        all_ticks = []
        max_retries = 3

        for chunk in self._chunked(keys, self.config.rest_batch_size):
            self._sleep_for_rate_limit()
            
            for attempt in range(max_retries):
                try:
                    url = self.adapter.get_ltp_url()
                    params = self.adapter.build_ltp_request(chunk)
                    
                    response = self.session.get(url, params=params, timeout=self.config.rest_timeout_seconds)
                    response.raise_for_status()
                    
                    ticks = self.adapter.parse_ltp_response(response.json(), self.config.instrument_map)
                    all_ticks.extend(ticks)
                    break
                except requests.RequestException as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to fetch REST batch after {max_retries} attempts: {e}")
                        raise
                    time.sleep(0.5 * (2 ** attempt))  # Exponential backoff
                    
        return all_ticks
