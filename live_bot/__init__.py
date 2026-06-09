"""
live_bot/
---------
Phase 7+: Live trading stack — live market feed, tick persistence,
paper/live order routing, and real-time risk checks.

Module layout:
    feeds/market_feed.py     — WebSocket + REST market feeds for Upstox
    feeds/portfolio_feed.py  — PortfolioDataStreamer wrapper for order/position updates
    storage.py               — Internal Parquet storage for raw feed, ticks, candles
    feeds/webhook_server.py  — FastAPI webhook receiver (Upstox postback URL)
    risk/risk_guard.py       — Daily loss limit, max positions, kill switch
    orders/paper_broker.py   — Paper trading order simulation (no real money)
    orders/live_broker.py    — Real order routing wrapper for Upstox
    engine.py                — LiveBotEngine: orchestrates all feeds + strategy
    candle_builder.py        — Assembles tick data into OHLCV 1-min bars
    state.py                 — Shared in-memory state (positions, P&L, ticks)
"""
