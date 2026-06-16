"""
live_bot/feeds/market_feed.py
------------------------------
Use cases:
    1. Subscribe to Upstox WebSocket market data and forward ticks into the
       live trading pipeline.
    2. Poll Upstox REST LTP quotes when the user prefers REST over WebSocket.
    3. Persist incoming ticks, build 1-minute candles, and notify the strategy
       engine from either source using the same downstream path.

This module intentionally supports both feed styles:
    - ``MarketFeed``     : WebSocket V3 streaming
    - ``RestMarketFeed`` : Batched REST polling via LTP Quotes V3

P2 FIX (2026-04-11) — IST constant extracted to config.py
==========================================================
Six live_bot modules each defined their own identical copy of:
    IST = timezone(timedelta(hours=5, minutes=30))

This was the same value, defined six times, with no canonical source.
Any future change (e.g. switching to ZoneInfo("Asia/Kolkata")) required
editing six files instead of one.

Fix: ``config.py`` now exports ``IST`` as a module-level constant.
This file removes its local definition and imports from config instead::

    from config import IST          # replaces local definition
"""


from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover - dependency optional in tests
    requests = None

from config import config, IST
from live_bot.candle_builder import candle_registry
from live_bot.storage import LiveMarketDataStorage, live_data_storage
from live_bot.state import TickData, state as live_state

logger = logging.getLogger(__name__)

LTP_V3_URL = f"{config.UPSTOX_BASE_URL}/v3/market-quote/ltp"

# Upstox docs: standard endpoints are rate limited per second and per minute.
# A 0.13s request spacing stays below both 50 req/sec and 500 req/min.
DEFAULT_REQUEST_SPACING_SECONDS = 0.13
DEFAULT_REST_BATCH_SIZE = 50

_KEY_TO_SYMBOL: Dict[str, str] = {}


def _parse_ltt(ltt_value: Any) -> datetime:
    """Parse a tick timestamp from the feed or REST response."""
    if ltt_value is None:
        return datetime.now(tz=IST)

    if isinstance(ltt_value, (int, float)):
        try:
            return datetime.fromtimestamp(ltt_value / 1000, tz=IST)
        except (ValueError, OSError, OverflowError):
            return datetime.now(tz=IST)

    if isinstance(ltt_value, datetime):
        if ltt_value.tzinfo is None:
            return ltt_value.replace(tzinfo=IST)
        return ltt_value.astimezone(IST)

    try:
        parsed = datetime.fromisoformat(str(ltt_value))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=IST)
        return parsed.astimezone(IST)
    except ValueError:
        return datetime.now(tz=IST)


def _extract_ohlc_from_feed(market_ff: dict) -> tuple[float, float, float, float, int]:
    """Extract 1-minute OHLC values from an Upstox WebSocket ``marketFF`` block."""
    try:
        market_ohlc = market_ff.get("marketOHLC", {})
        ohlc_list = market_ohlc.get("ohlc", [])
        if not ohlc_list:
            return 0.0, 0.0, 0.0, 0.0, 0

        target = None
        for candle in ohlc_list:
            if candle.get("interval") == "I1":
                target = candle
                break
        if target is None:
            target = ohlc_list[0]

        return (
            float(target.get("open", 0) or 0),
            float(target.get("high", 0) or 0),
            float(target.get("low", 0) or 0),
            float(target.get("close", 0) or 0),
            int(target.get("volume", 0) or 0),
        )
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        logger.debug("OHLC extraction error: %s", exc)
        return 0.0, 0.0, 0.0, 0.0, 0


def _parse_message(message: dict) -> List[TickData]:
    """Parse a WebSocket V3 message into ``TickData`` objects."""
    results: List[TickData] = []
    if not isinstance(message, dict):
        return results

    feeds = message.get("feeds", {})
    if not feeds:
        return results

    for instrument_key, feed_data in feeds.items():
        try:
            symbol = _KEY_TO_SYMBOL.get(instrument_key, instrument_key.split("|")[-1])
            full_feed = feed_data.get("fullFeed", {})
            market_ff = full_feed.get("marketFF", {})
            ltpc = market_ff.get("ltpc", {})

            ltp = float(ltpc.get("ltp", 0) or 0)
            if ltp <= 0:
                continue

            e_feed = market_ff.get("eFeedDetails", {})
            candle_open, candle_high, candle_low, candle_close, candle_volume = (
                _extract_ohlc_from_feed(market_ff)
            )

            # Extract top bid/ask from marketLevel.bidAskQuote
            market_level = market_ff.get("marketLevel", {})
            bid_ask_quote = market_level.get("bidAskQuote", [])
            top_bid_price = 0.0
            top_bid_qty = 0
            top_ask_price = 0.0
            top_ask_qty = 0
            if bid_ask_quote and isinstance(bid_ask_quote, list) and len(bid_ask_quote) > 0:
                top_quote = bid_ask_quote[0]
                top_bid_price = float(top_quote.get("bidP", 0) or 0)
                top_bid_qty = int(top_quote.get("bidQ", 0) or 0)
                top_ask_price = float(top_quote.get("askP", 0) or 0)
                top_ask_qty = int(top_quote.get("askQ", 0) or 0)

            results.append(
                TickData(
                    instrument_key=instrument_key,
                    symbol=symbol,
                    ltp=ltp,
                    ltt=_parse_ltt(ltpc.get("ltt")),
                    ltq=int(ltpc.get("ltq", 0) or 0),
                    close_price=float(ltpc.get("cp", 0) or 0),
                    open_price=float(e_feed.get("open", ltp) or ltp),
                    high_price=float(e_feed.get("high", ltp) or ltp),
                    low_price=float(e_feed.get("low", ltp) or ltp),
                    volume=int(e_feed.get("vtt", 0) or 0),
                    oi=float(e_feed.get("oi", 0) or 0),
                    candle_open=candle_open,
                    candle_high=candle_high,
                    candle_low=candle_low,
                    candle_close=candle_close,
                    candle_volume=candle_volume,
                    top_bid_price=top_bid_price,
                    top_bid_qty=top_bid_qty,
                    top_ask_price=top_ask_price,
                    top_ask_qty=top_ask_qty,
                )
            )
        except Exception as exc:
            logger.warning("Error parsing WebSocket feed for %s: %s", instrument_key, exc)
    return results


def _dispatch_tick(
    tick: TickData,
    on_candle_complete: Optional[Callable[[str, dict], None]],
    data_storage: Optional[LiveMarketDataStorage],
) -> None:
    """Push one tick through state, persistence, candle-building, and callbacks."""
    live_state.update_tick(tick.symbol, tick)

    if data_storage is not None:
        data_storage.record_tick(tick)

    try:
        completed_candle = candle_registry.on_tick(tick.symbol, tick)
    except Exception as exc:
        logger.debug("[MarketFeed] Candle build error for %s: %s", tick.symbol, exc)
        completed_candle = None

    if completed_candle is not None and data_storage is not None:
        try:
            data_storage.record_candle(tick.symbol, completed_candle.to_dict())
        except Exception as exc:
            logger.error("[MarketFeed] Candle persistence error for %s: %s", tick.symbol, exc)

    if completed_candle is not None and on_candle_complete is not None:
        try:
            on_candle_complete(tick.symbol, completed_candle.to_dict())
        except Exception as exc:
            logger.error(
                "[MarketFeed] on_candle_complete callback error for %s: %s",
                tick.symbol,
                exc,
            )


def _chunked(items: Iterable[str], size: int) -> List[List[str]]:
    values = list(items)
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    return [values[index:index + size] for index in range(0, len(values), size)]


def _parse_rest_payload(
    payload: dict,
    instrument_map: Dict[str, str],
    timestamp: Optional[datetime] = None,
) -> List[TickData]:
    """Parse Upstox LTP Quotes V3 response payload into ``TickData`` objects."""
    results: List[TickData] = []
    if not isinstance(payload, dict):
        return results

    data = payload.get("data", {})
    if not isinstance(data, dict):
        return results

    tick_time = timestamp or datetime.now(tz=IST)
    for instrument_key, row in data.items():
        if not isinstance(row, dict):
            continue

        last_price = float(row.get("last_price", 0) or 0)
        if last_price <= 0:
            continue

        symbol = instrument_map.get(instrument_key, _KEY_TO_SYMBOL.get(instrument_key))
        if not symbol:
            symbol = instrument_key.split("|")[-1]

        close_price = float(row.get("cp", last_price) or last_price)
        volume = int(row.get("volume", 0) or 0)
        ltq = int(row.get("ltq", 0) or 0)
        results.append(
            TickData(
                instrument_key=instrument_key,
                symbol=symbol,
                ltp=last_price,
                ltt=tick_time,
                ltq=ltq,
                close_price=close_price,
                open_price=last_price,
                high_price=last_price,
                low_price=last_price,
                volume=volume,
                oi=0.0,
                candle_open=0.0,
                candle_high=0.0,
                candle_low=0.0,
                candle_close=0.0,
                candle_volume=0,
            )
        )
    return results


class BaseMarketFeed:
    """Common interface shared by WebSocket and REST feeds."""

    def start(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError


class MarketFeed(BaseMarketFeed):
    """Upstox WebSocket V3 market feed wrapper."""

    def __init__(
        self,
        access_token: str,
        instrument_map: Dict[str, str],
        on_candle_complete: Optional[Callable[[str, dict], None]] = None,
        on_raw_message: Optional[Callable[[dict], None]] = None,
        mode: str = "full",
        auto_reconnect_interval: int = 5,
        auto_reconnect_retries: int = 50,
        data_storage: Optional[LiveMarketDataStorage] = live_data_storage,
    ) -> None:
        self._access_token = access_token
        self._instrument_map = instrument_map
        self._on_candle_complete = on_candle_complete
        self._on_raw_message = on_raw_message
        self._mode = mode
        self._reconnect_interval = auto_reconnect_interval
        self._reconnect_retries = auto_reconnect_retries
        self._data_storage = data_storage

        self._streamer = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        _KEY_TO_SYMBOL.update(instrument_map)

    def start(self) -> None:
        if self._is_running:
            logger.warning("[MarketFeed] Already running.")
            return
        self._is_running = True
        self._thread = threading.Thread(
            target=self._run,
            name="MarketFeedThread",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            import upstox_client

            configuration = upstox_client.Configuration()
            configuration.access_token = self._access_token

            self._streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(configuration),
                list(self._instrument_map.keys()),
                self._mode,
            )
            self._streamer.auto_reconnect(
                True,
                self._reconnect_interval,
                self._reconnect_retries,
            )
            self._streamer.on("open", self._on_open)
            self._streamer.on("message", self._on_message)
            self._streamer.on("error", self._on_error)
            self._streamer.on("close", self._on_close)
            self._streamer.on("reconnecting", self._on_reconnecting)
            self._streamer.on("autoReconnectStopped", self._on_reconnect_stopped)
            self._streamer.connect()
        except ImportError:
            logger.error("[MarketFeed] upstox_client is not installed.")
            live_state.set_market_feed_status(False)
            live_state.log_activity(
                "FEED_ERROR",
                "upstox_client not installed. Cannot start market feed.",
                level="ERROR",
            )
        except Exception as exc:
            logger.error("[MarketFeed] Fatal error: %s", exc, exc_info=True)
            live_state.set_market_feed_status(False)
            live_state.log_activity("FEED_ERROR", f"Feed thread crashed: {exc}", level="ERROR")

    def _on_open(self, *args: Any, **kwargs: Any) -> None:
        live_state.set_market_feed_status(True)
        live_state.log_activity("FEED_CONNECTED", "Market data WebSocket connected.")

    def _on_message(self, message: dict) -> None:
        if not message:
            return
        if self._data_storage is not None:
            try:
                self._data_storage.record_raw_message(message, self._instrument_map)
            except Exception as exc:
                logger.error("[MarketFeed] Raw message persistence error: %s", exc)
        if self._on_raw_message is not None:
            try:
                self._on_raw_message(message)
            except Exception as exc:
                logger.error("[MarketFeed] Raw message callback error: %s", exc)
        try:
            ticks = _parse_message(message)
        except Exception as exc:
            logger.debug("[MarketFeed] Message parse error: %s", exc)
            return

        for tick in ticks:
            _dispatch_tick(tick, self._on_candle_complete, self._data_storage)

    def _on_error(self, error: Any, *args: Any, **kwargs: Any) -> None:
        logger.error("[MarketFeed] WebSocket error: %s", error)
        live_state.set_market_feed_status(False)
        live_state.log_activity("FEED_ERROR", f"WebSocket error: {error}", level="ERROR")

    def _on_close(self, *args: Any, **kwargs: Any) -> None:
        live_state.set_market_feed_status(False)
        live_state.log_activity("FEED_DISCONNECTED", "Market data WebSocket disconnected.")

    def _on_reconnecting(self, *args: Any, **kwargs: Any) -> None:
        live_state.log_activity("FEED_RECONNECTING", "Attempting to reconnect market feed...")

    def _on_reconnect_stopped(self, msg: Any = None, *args: Any, **kwargs: Any) -> None:
        error_msg = f"Auto-reconnect stopped after {self._reconnect_retries} attempts."
        logger.critical("[MarketFeed] %s", error_msg)
        live_state.set_market_feed_status(False)
        live_state.log_activity("FEED_RECONNECT_FAILED", error_msg, level="CRITICAL")
        live_state.activate_kill_switch("Market feed permanently disconnected.")

    def subscribe(self, instrument_keys: List[str]) -> None:
        if self._streamer is None:
            logger.warning("[MarketFeed] Cannot subscribe before streamer initialisation.")
            return
        try:
            self._streamer.subscribe(instrument_keys, self._mode)
        except Exception as exc:
            logger.error("[MarketFeed] Subscribe error: %s", exc)

    def unsubscribe(self, instrument_keys: List[str]) -> None:
        if self._streamer is None:
            return
        try:
            self._streamer.unsubscribe(instrument_keys)
        except Exception as exc:
            logger.error("[MarketFeed] Unsubscribe error: %s", exc)

    def change_mode(self, instrument_keys: List[str], new_mode: str) -> None:
        if self._streamer is None:
            return
        try:
            self._streamer.change_mode(instrument_keys, new_mode)
        except Exception as exc:
            logger.error("[MarketFeed] change_mode error: %s", exc)

    def stop(self) -> None:
        self._is_running = False
        if self._streamer is not None:
            try:
                self._streamer.disconnect()
            except Exception as exc:
                logger.warning("[MarketFeed] Disconnect error: %s", exc)
        if self._data_storage is not None:
            try:
                self._data_storage.close()
            except Exception as exc:
                logger.warning("[MarketFeed] Data storage close error: %s", exc)
        live_state.set_market_feed_status(False)

    @property
    def is_connected(self) -> bool:
        return live_state._market_feed_connected


class RestMarketFeed(BaseMarketFeed):
    """
    Poll Upstox LTP Quotes V3 in batches and route them through the live pipeline.

    REST mode is useful when the user explicitly prefers request/response style
    data collection over WebSocket streaming. It remains more limited than the
    WebSocket feed because Upstox only returns LTP-centric fields here.
    """

    def __init__(
        self,
        access_token: str,
        instrument_map: Dict[str, str],
        on_candle_complete: Optional[Callable[[str, dict], None]] = None,
        poll_interval_seconds: float = 1.0,
        request_spacing_seconds: float = DEFAULT_REQUEST_SPACING_SECONDS,
        batch_size: int = DEFAULT_REST_BATCH_SIZE,
        timeout_seconds: float = 10.0,
        max_consecutive_failures: int = 5,
        data_storage: Optional[LiveMarketDataStorage] = live_data_storage,
        session: Optional[Any] = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")
        if request_spacing_seconds <= 0:
            raise ValueError("request_spacing_seconds must be > 0")
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")

        self._access_token = access_token
        self._instrument_map = instrument_map
        self._on_candle_complete = on_candle_complete
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._request_spacing_seconds = max(
            float(request_spacing_seconds),
            DEFAULT_REQUEST_SPACING_SECONDS,
        )
        self._batch_size = int(batch_size)
        self._timeout_seconds = float(timeout_seconds)
        self._max_consecutive_failures = int(max_consecutive_failures)
        self._data_storage = data_storage
        self._session = session
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._consecutive_failures = 0
        self._last_request_started = 0.0

        _KEY_TO_SYMBOL.update(instrument_map)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("[RestMarketFeed] Already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="RestMarketFeedThread",
            daemon=True,
        )
        self._thread.start()

    def _get_session(self) -> Any:
        if self._session is not None:
            return self._session
        if requests is None:
            raise RuntimeError("The 'requests' package is required for REST feed mode.")
        self._session = requests.Session()
        return self._session

    def _sleep_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_started
        remaining = self._request_spacing_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _fetch_batch(self, instrument_keys: List[str]) -> List[TickData]:
        self._sleep_for_rate_limit()
        self._last_request_started = time.monotonic()

        session = self._get_session()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        response = session.get(
            LTP_V3_URL,
            params={"instrument_key": ",".join(instrument_keys)},
            headers=headers,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return _parse_rest_payload(payload, self._instrument_map, datetime.now(tz=IST))

    def _run(self) -> None:
        live_state.set_market_feed_status(True)
        live_state.log_activity("FEED_CONNECTED", "REST market feed polling started.")
        batches = _chunked(list(self._instrument_map.keys()), self._batch_size)

        while not self._stop_event.is_set():
            cycle_started = time.monotonic()
            any_success = False

            for batch in batches:
                if self._stop_event.is_set():
                    break
                try:
                    ticks = self._fetch_batch(batch)
                    for tick in ticks:
                        _dispatch_tick(tick, self._on_candle_complete, self._data_storage)
                    any_success = True
                    self._consecutive_failures = 0
                except Exception as exc:
                    self._consecutive_failures += 1
                    logger.warning(
                        "[RestMarketFeed] Batch fetch failed (%s/%s): %s",
                        self._consecutive_failures,
                        self._max_consecutive_failures,
                        exc,
                    )
                    live_state.log_activity(
                        "FEED_ERROR",
                        f"REST feed batch failed: {exc}",
                        level="WARNING",
                    )
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        live_state.set_market_feed_status(False)
                        live_state.activate_kill_switch(
                            "REST market feed failed repeatedly."
                        )
                        return

            if any_success:
                live_state.set_market_feed_status(True)

            elapsed = time.monotonic() - cycle_started
            sleep_seconds = max(0.0, self._poll_interval_seconds - elapsed)
            self._stop_event.wait(sleep_seconds)

        live_state.set_market_feed_status(False)
        live_state.log_activity("FEED_DISCONNECTED", "REST market feed polling stopped.")

    def stop(self) -> None:
        self._stop_event.set()
        session = self._session
        if session is not None and hasattr(session, "close"):
            try:
                session.close()
            except Exception:
                pass
        if self._data_storage is not None:
            try:
                self._data_storage.close()
            except Exception:
                pass
        live_state.set_market_feed_status(False)

    @property
    def is_connected(self) -> bool:
        return live_state._market_feed_connected


__all__ = [
    "BaseMarketFeed",
    "DEFAULT_REST_BATCH_SIZE",
    "DEFAULT_REQUEST_SPACING_SECONDS",
    "IST",
    "LTP_V3_URL",
    "MarketFeed",
    "RestMarketFeed",
    "_extract_ohlc_from_feed",
    "_parse_ltt",
    "_parse_message",
    "_parse_rest_payload",
]