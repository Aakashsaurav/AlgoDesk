# Live Bot Feeds

This folder now supports both Upstox live-data paths that matter for the live bot:

- `MarketFeed`: WebSocket V3 streaming. Best choice for continuous live trading because it carries richer payloads, lower latency, and higher subscription limits.
- `RestMarketFeed`: batched polling of `v3/market-quote/ltp`. Useful when the user explicitly wants REST-based capture or needs a fallback mode.
- `LiveMarketDataStorage`: writes raw feed rows, normalized ticks, and completed candles internally under `data/live_ticks/`.

## Common Pipeline

Both feed types use the same downstream flow:

1. Parse raw Upstox response into `TickData`
2. Update `live_bot.state`
3. Persist raw payload + normalized tick internally through `LiveMarketDataStorage`
4. Send the tick into `CandleRegistry`
5. Notify `LiveBotEngine` when a candle completes

This keeps the strategy layer feed-agnostic.

## Rate-Limit Handling

`RestMarketFeed` is intentionally conservative.

- It batches instrument keys instead of sending one request per symbol.
- It enforces a minimum request spacing so the bot stays below Upstox standard endpoint limits.
- It trips the live kill switch after repeated REST failures instead of silently running blind.

## Configuration

`live_bot.engine.LiveBotConfig` controls the mode:

- `feed_type="websocket"` uses `MarketFeed`
- `feed_type="rest"` uses `RestMarketFeed`
- `rest_poll_interval_seconds`, `rest_request_spacing_seconds`, and `rest_batch_size` control REST polling behaviour

Example:

```python
bot_cfg = LiveBotConfig(
    strategy_class=MyStrategy,
    instrument_map={"NSE_EQ|INE020B01018": "RELIANCE"},
    feed_type="rest",
    rest_poll_interval_seconds=1.0,
    rest_batch_size=25,
)
```

## Tick Storage Notes

Storage format:
- Parquet with `zstd` compression is used because live full-mode market data grows fast, and Parquet is materially smaller and faster to query than CSV/JSONL for long-running capture.

What is stored internally:
- `raw/` keeps one row per instrument per feed message with the original message payload, full feed JSON, market depth JSON, OHLC JSON, and extracted scalar fields such as LTP, ATP, OI, VTT, circuits, and timestamps.
- `ticks/` keeps normalized `TickData` rows used by the live bot runtime.
- `candles/` keeps completed 1-minute candles emitted by `CandleRegistry`.

Partitioning:
- Files are chunked and partitioned by dataset, symbol, trading date, and hour:
  `data/live_ticks/<dataset>/<SYMBOL>/<YYYY-MM-DD>/<HH>/*.parquet`

Why this is preferred:
- small chunk files avoid large append rewrites
- compressed columnar layout keeps disk usage manageable
- raw and normalized datasets stay available for both replay and analytics
