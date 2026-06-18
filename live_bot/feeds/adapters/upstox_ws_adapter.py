import logging
from typing import Any
from datetime import datetime
from live_bot.models import (
    TickData, PortfolioUpdate, FeedMode, FeedSource,
    LTPCData, MarketDepthLevel, OHLCCandle, OptionGreeks
)
from live_bot.feeds.base import FeedAdapterBase
from config import IST

logger = logging.getLogger(__name__)

class UpstoxWebSocketAdapter(FeedAdapterBase):
    def __init__(self):
        self._key_to_symbol: dict[str, str] = {}

    def parse_market_message(
        self,
        raw_message: dict,
        instrument_map: dict[str, str],
    ) -> list[TickData]:
        self._key_to_symbol.update(instrument_map)
        results = []
        
        if not isinstance(raw_message, dict):
            return results

        feeds = raw_message.get("feeds", {})
        if not feeds:
            return results

        for instrument_key, feed_data in feeds.items():
            try:
                symbol = self._key_to_symbol.get(instrument_key, instrument_key.split("|")[-1])
                
                # Upstox feed wrapper
                full_feed = feed_data.get("fullFeed", {})
                
                # Check feed type
                is_index = "indexFF" in full_feed
                ff_block = full_feed.get("indexFF", {}) if is_index else full_feed.get("marketFF", {})
                
                ltpc_dict = ff_block.get("ltpc", {})
                ltp = float(ltpc_dict.get("ltp", 0) or 0)
                
                if ltp <= 0:
                    continue
                    
                # Determine feed mode from data presence
                market_level = ff_block.get("marketLevel", {})
                bid_ask = market_level.get("bidAskQuote", [])
                greeks_dict = ff_block.get("optionGreeks")
                
                if greeks_dict:
                    mode = FeedMode.OPTION_GREEKS
                elif bid_ask and len(bid_ask) > 5:
                    mode = FeedMode.FULL_D30
                elif bid_ask:
                    mode = FeedMode.FULL
                else:
                    mode = FeedMode.LTPC

                # Parse components
                ltpc_data = self._parse_ltpc(ltpc_dict)
                depth_5 = self._parse_depth(bid_ask, 5) if mode in (FeedMode.FULL, FeedMode.FULL_D30) else None
                depth_30 = self._parse_depth(bid_ask, 30) if mode == FeedMode.FULL_D30 else None
                
                ohlc_dict_list = ff_block.get("marketOHLC", {}).get("ohlc", [])
                ohlc_candles = self._parse_ohlc_candles(ohlc_dict_list) if mode != FeedMode.LTPC else None
                
                greeks_data = self._parse_greeks(greeks_dict) if mode == FeedMode.OPTION_GREEKS else None
                
                # Extras
                e_feed = ff_block.get("eFeedDetails", {})
                
                tick = TickData(
                    instrument_key=instrument_key,
                    symbol=symbol,
                    feed_mode=mode,
                    feed_source=FeedSource.WEBSOCKET,
                    received_at=datetime.now(tz=IST),
                    ltpc=ltpc_data,
                    depth_5=depth_5,
                    depth_30=depth_30,
                    ohlc_candles=ohlc_candles,
                    yearly_high=float(ff_block.get("yh", e_feed.get("yh", 0)) or 0) or None,
                    yearly_low=float(ff_block.get("yl", e_feed.get("yl", 0)) or 0) or None,
                    volume=int(e_feed.get("v", 0) or 0) or 0,
                    atp=float(e_feed.get("atp", 0) or 0) or None,
                    total_buy_qty=int(e_feed.get("tbq", 0) or 0) or None,
                    total_sell_qty=int(e_feed.get("tsq", 0) or 0) or None,
                    lower_circuit=float(e_feed.get("lowerCP", 0) or 0) or None,
                    upper_circuit=float(e_feed.get("upperCP", 0) or 0) or None,
                    oi=float(e_feed.get("oi", 0) or 0) or None,
                    greeks=greeks_data
                )
                results.append(tick)
            except Exception as e:
                logger.error(f"Error parsing websocket message for {instrument_key}: {e}")
                
        return results

    def _parse_ltpc(self, ltpc: dict) -> LTPCData:
        return LTPCData(
            ltp=float(ltpc.get("ltp", 0) or 0),
            ltt=self._parse_ltt(ltpc.get("ltt")),
            ltq=int(ltpc.get("ltq", 0) or 0),
            close_price=float(ltpc.get("cp", 0) or 0)
        )

    def _parse_depth(self, bid_ask_quote: list, levels: int) -> list[MarketDepthLevel]:
        depth = []
        if not bid_ask_quote:
            return depth
        for i in range(min(len(bid_ask_quote), levels)):
            quote = bid_ask_quote[i]
            depth.append(MarketDepthLevel(
                bid_price=float(quote.get("bq", 0) or 0),
                bid_qty=int(quote.get("bq", 0) or 0),
                bid_orders=int(quote.get("bno", 0) or 0),
                ask_price=float(quote.get("ap", 0) or 0),
                ask_qty=int(quote.get("aq", 0) or 0),
                ask_orders=int(quote.get("ano", 0) or 0)
            ))
        return depth

    def _parse_ohlc_candles(self, ohlc_list: list) -> list[OHLCCandle]:
        candles = []
        if not ohlc_list:
            return candles
        for candle in ohlc_list:
            candles.append(OHLCCandle(
                interval=candle.get("interval", ""),
                open=float(candle.get("open", 0) or 0),
                high=float(candle.get("high", 0) or 0),
                low=float(candle.get("low", 0) or 0),
                close=float(candle.get("close", 0) or 0),
                volume=int(candle.get("volume", 0) or 0),
                timestamp=self._parse_ltt(candle.get("ts"))
            ))
        return candles

    def _parse_greeks(self, greeks_dict: dict | None) -> OptionGreeks | None:
        if not greeks_dict:
            return None
        return OptionGreeks(
            option_price=float(greeks_dict.get("op", 0) or 0),
            underlying_price=float(greeks_dict.get("up", 0) or 0),
            implied_volatility=float(greeks_dict.get("iv", 0) or 0),
            delta=float(greeks_dict.get("delta", 0) or 0),
            theta=float(greeks_dict.get("theta", 0) or 0),
            gamma=float(greeks_dict.get("gamma", 0) or 0),
            vega=float(greeks_dict.get("vega", 0) or 0),
            rho=float(greeks_dict.get("rho", 0) or 0)
        )

    def _parse_ltt(self, ltt_value: Any) -> datetime:
        if ltt_value is None:
            return datetime.now(tz=IST)
        if isinstance(ltt_value, (int, float)):
            try:
                # Upstox returns epoch in milliseconds
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

    def parse_portfolio_message(
        self,
        raw_message: dict,
    ) -> PortfolioUpdate | None:
        if not raw_message:
            return None
        try:
            update_type = raw_message.get("update_type", "unknown")
            return PortfolioUpdate(
                update_type=update_type,
                order_id=raw_message.get("order_id"),
                status=raw_message.get("status"),
                instrument_key=raw_message.get("instrument_token"),
                transaction_type=raw_message.get("transaction_type"),
                quantity=int(raw_message.get("quantity", 0) or 0),
                average_price=float(raw_message.get("average_price", 0) or 0),
                filled_quantity=int(raw_message.get("filled_quantity", 0) or 0),
                raw=raw_message,
                received_at=datetime.now(tz=IST)
            )
        except Exception as e:
            logger.error(f"Error parsing portfolio update: {e}")
            return None

    def parse_rest_quote(
        self,
        raw_response: dict,
        instrument_map: dict[str, str],
    ) -> list[TickData]:
        self._key_to_symbol.update(instrument_map)
        results = []
        
        data = raw_response.get("data", {})
        for instrument_key, quote_data in data.items():
            try:
                symbol = self._key_to_symbol.get(instrument_key, instrument_key.split("|")[-1])
                ltp = float(quote_data.get("last_price", 0) or 0)
                
                if ltp <= 0:
                    continue
                    
                # From REST v3/market-quote/ltp API, we only get LTP mostly, or if it's quotes, more data.
                # Assuming simple LTP format first
                ltpc_data = LTPCData(
                    ltp=ltp,
                    ltt=self._parse_ltt(quote_data.get("last_trade_time")),
                    ltq=int(quote_data.get("last_trade_quantity", 0) or 0),
                    close_price=float(quote_data.get("close_price", 0) or 0)
                )
                
                tick = TickData(
                    instrument_key=instrument_key,
                    symbol=symbol,
                    feed_mode=FeedMode.LTPC,
                    feed_source=FeedSource.REST,
                    received_at=datetime.now(tz=IST),
                    ltpc=ltpc_data,
                    atp=float(quote_data.get("average_trade_price", 0) or 0) or None,
                    total_buy_qty=int(quote_data.get("total_buy_quantity", 0) or 0) or None,
                    total_sell_qty=int(quote_data.get("total_sell_quantity", 0) or 0) or None,
                    lower_circuit=float(quote_data.get("lower_circuit_limit", 0) or 0) or None,
                    upper_circuit=float(quote_data.get("upper_circuit_limit", 0) or 0) or None,
                    oi=float(quote_data.get("open_interest", 0) or 0) or None,
                )
                results.append(tick)
            except Exception as e:
                logger.error(f"Error parsing REST quote for {instrument_key}: {e}")
                
        return results

    def get_websocket_subscribe_payload(
        self,
        instrument_keys: list[str],
        mode: FeedMode,
    ) -> dict:
        return {
            "guid": "someguid",
            "method": "sub",
            "data": {
                "mode": mode.value,
                "instrumentKeys": instrument_keys
            }
        }
