import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Type
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from config import config, IST
from live_bot.config import LiveBotConfig
from live_bot.state import state as live_state
from live_bot.candle_builder import candle_registry
from live_bot.feeds.feed_manager import FeedManager
from live_bot.session_manager import SessionManager
from live_bot.orders.adapters.upstox_order_adapter import UpstoxOrderAdapter
from risk import LiveRiskGuard, RiskConfig
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

class LiveBotEngine:
    """
    Main live trading engine.
    Coordinates feeds, strategy, risk management, and order execution.
    """

    def __init__(self, bot_config: LiveBotConfig, access_token: str):
        self._config       = bot_config
        self._access_token = access_token

        params = bot_config.strategy_params or {}
        if isinstance(params, dict):
            self._strategy = bot_config.strategy_class(**params)
        else:
            self._strategy = bot_config.strategy_class(params)
        
        risk_config = RiskConfig(
            initial_capital=bot_config.initial_capital,
            max_daily_loss_pct=bot_config.daily_loss_limit_pct,
            max_drawdown_pct=bot_config.max_drawdown_pct,
            max_positions=bot_config.max_open_positions,
            max_position_size_pct=bot_config.max_position_pct,
            allow_shorting=bot_config.allow_short
        )
        self._risk = LiveRiskGuard(config=risk_config)
        
        # I9. Paper vs Live selection uses config.paper_trade
        if bot_config.paper_trade:
            from live_bot.orders.paper_broker import PaperBroker
            self._broker = PaperBroker(product=bot_config.product)
            logger.info("[LiveBotEngine] Running in PAPER TRADE mode.")
        else:
            from live_bot.orders.live_broker import LiveBroker
            self._broker = LiveBroker(product=bot_config.product, access_token=self._access_token)
            logger.info("[LiveBotEngine] Running in LIVE TRADE mode.")

        # I7. Wire FeedManager
        adapter = UpstoxOrderAdapter(access_token)
        self._feed_manager = FeedManager(
            bot_config, 
            adapter, 
            access_token,
            on_tick=self._on_tick,
            on_candle_complete=self._on_candle_complete,
            on_portfolio_update=self._on_portfolio_update
        )

        # I8. Wire SessionManager
        from live_bot.storage.session_store import SessionStore
        from live_bot.storage.tick_store import TickStoreManager
        from live_bot.storage.candle_store import CandleStore
        import os
        # Initialize stores with standard paths
        db_path = os.path.join("data", "sessions.sqlite")
        os.makedirs("data", exist_ok=True)
        session_store = SessionStore(db_path)
        
        from datetime import datetime; from config import IST
        tick_store = TickStoreManager(os.path.join("data", "ticks"), datetime.now(tz=IST).date())
        candle_store = CandleStore(os.path.join("data", "candles"), datetime.now(tz=IST).date())
        self._session_manager = SessionManager(session_store, tick_store, candle_store, live_state)

        self._candle_queue: queue.Queue = queue.Queue(maxsize=100)
        self._strategy_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._squareoff_thread: Optional[threading.Thread] = None

        logger.info(
            f"[LiveBotEngine] Initialised. Strategy={self._strategy.__class__.__name__} "
            f"Paper={bot_config.paper_trade} Feed={bot_config.feed_type} "
            f"Capital=₹{bot_config.initial_capital:,.0f}"
        )
        self._instrument_meta_by_key: Optional[Dict[str, Dict[str, Any]]] = None

    def start(self) -> None:
        if live_state._is_running:
            logger.warning("[LiveBotEngine] Already running. Call stop() first.")
            return

        cfg = self._config
        symbols = list(cfg.instrument_map.values())

        live_state.set_initial_capital(cfg.initial_capital)
        live_state.set_active_strategy(self._strategy.__class__.__name__)
        live_state.set_subscribed_symbols(symbols)
        live_state.set_running(True)
        self._stop_event.clear()

        logger.info(f"[LiveBotEngine] Starting bot for symbols: {symbols}")
        live_state.log_activity("BOT_START", f"🚀 Bot started | Strategy: {self._strategy.__class__.__name__} | Symbols: {', '.join(symbols)} | Capital: ₹{cfg.initial_capital:,.0f}")

        # I8. start() calls session_manager.start_session()
        self._session_manager.start_session()

        self._seed_candles()
        self._feed_manager.start()

        self._strategy_thread = threading.Thread(target=self._strategy_loop, name="StrategyThread", daemon=True)
        self._strategy_thread.start()

        self._squareoff_thread = threading.Thread(target=self._squareoff_monitor, name="SquareoffThread", daemon=True)
        self._squareoff_thread.start()

        logger.info("[LiveBotEngine] ✅ All components started.")

    def stop(self) -> None:
        logger.info("[LiveBotEngine] Stopping...")
        live_state.log_activity("BOT_STOP", "🛑 Bot stop requested.")
        self._stop_event.set()
        
        self._feed_manager.stop()
        
        # I8. stop() calls session_manager.end_session()
        self._session_manager.end_session()

        live_state.set_running(False)
        logger.info("[LiveBotEngine] Stopped.")

    def activate_kill_switch(self, reason: str = "") -> None:
        live_state.activate_kill_switch(reason)
        self._broker.squareoff_all()

    # I2. Parallelise seed loading
    def _seed_candles(self) -> None:
        cfg = self._config
        max_rows = max(cfg.seed_lookback_days * 375, cfg.min_bars_required)
        
        with ThreadPoolExecutor(max_workers=min(10, len(cfg.instrument_map))) as executor:
            futures = []
            for instrument_key, symbol in cfg.instrument_map.items():
                futures.append(executor.submit(self._seed_one_symbol, instrument_key, symbol, max_rows))
            for f in futures:
                f.result() # wait for all

    def _seed_one_symbol(self, instrument_key: str, symbol: str, max_rows: int) -> None:
        cfg = self._config
        try:
            lookup = self._resolve_seed_lookup(instrument_key, symbol)
            if lookup is None:
                logger.warning(f"[LiveBotEngine] Could not resolve lookup for {symbol}. Continuing without seed data.")
                candle_registry.register(symbol, seed_df=None, max_history_bars=max_rows)
                return

            from broker.upstox.data_manager import get_ohlcv
            df = get_ohlcv(
                instrument_type=lookup["instrument_type"],
                exchange=lookup["exchange"],
                trading_symbol=lookup["trading_symbol"],
                unit="minutes",
                interval=1,
                period=f"{cfg.seed_lookback_days}days",
                option_type=lookup.get("option_type"),
                expiry=lookup.get("expiry"),
                strike=lookup.get("strike"),
            )

            if df is not None and not df.empty:
                if len(df) > max_rows:
                    df = df.tail(max_rows).copy()
                logger.info(f"[LiveBotEngine] Seeding {symbol} with {len(df)} historical minute bars.")
                candle_registry.register(symbol, seed_df=df, max_history_bars=max_rows)
            else:
                logger.warning(f"[LiveBotEngine] No historical data for {symbol}.")
                candle_registry.register(symbol, seed_df=None, max_history_bars=max_rows)
        except Exception as e:
            logger.error(f"[LiveBotEngine] Error seeding {symbol}: {e}", exc_info=False)
            candle_registry.register(symbol, seed_df=None, max_history_bars=max_rows)

    def _resolve_seed_lookup(self, instrument_key: str, symbol: str) -> Optional[Dict[str, Any]]:
        instrument = self._get_instrument_meta(instrument_key)
        if instrument is None:
            return self._fallback_seed_lookup(instrument_key, symbol)

        segment = str(instrument.get("segment", "")).upper()
        exchange = str(instrument.get("exchange", "")).upper() or self._segment_exchange(segment)
        raw_type = str(instrument.get("instrument_type", "")).upper()
        asset_type = str(instrument.get("asset_type", "")).upper()
        trading_symbol = instrument.get("asset_symbol") or instrument.get("trading_symbol") or symbol

        lookup: Dict[str, Any] = {"exchange": exchange, "trading_symbol": str(trading_symbol)}

        if segment in {"NSE_EQ", "BSE_EQ"}:
            lookup["instrument_type"] = "EQUITY"
            return lookup
        if segment in {"NSE_INDEX", "BSE_INDEX"}:
            lookup["instrument_type"] = "INDEX"
            return lookup
        if raw_type == "FUT":
            future_map = {"EQUITY": "FUTSTK", "INDEX": "FUTIDX", "COM": "FUTCOM", "CUR": "FUTCUR", "IRD": "FUTIRT"}
            lookup["instrument_type"] = future_map.get(asset_type)
            lookup["expiry"] = self._format_expiry(instrument.get("expiry"))
            return lookup if lookup["instrument_type"] and lookup["expiry"] else None
        if raw_type in {"CE", "PE"}:
            option_map = {"EQUITY": "OPTSTK", "INDEX": "OPTIDX", "COM": "OPTCOM", "CUR": "OPTCUR", "IRD": "OPTIRD"}
            lookup["instrument_type"] = option_map.get(asset_type)
            lookup["option_type"] = raw_type
            lookup["expiry"] = self._format_expiry(instrument.get("expiry"))
            strike = instrument.get("strike_price")
            lookup["strike"] = float(strike) if strike is not None else None
            return lookup if lookup["instrument_type"] and lookup["expiry"] and lookup["strike"] is not None else None
        return self._fallback_seed_lookup(instrument_key, symbol)

    def _get_instrument_meta(self, instrument_key: str) -> Optional[Dict[str, Any]]:
        if self._instrument_meta_by_key is None:
            try:
                from broker.upstox.instrument_manager import download_and_save_instrument_list
                instrument_data = download_and_save_instrument_list()
                self._instrument_meta_by_key = {str(row.get("instrument_key", "")): row for row in instrument_data if row.get("instrument_key")}
            except Exception as exc:
                logger.warning("[LiveBotEngine] Could not load instrument metadata for seeding: %s", exc)
                self._instrument_meta_by_key = {}
        return self._instrument_meta_by_key.get(instrument_key)

    @staticmethod
    def _fallback_seed_lookup(instrument_key: str, symbol: str) -> Optional[Dict[str, Any]]:
        segment = instrument_key.split("|", 1)[0].upper()
        if segment == "NSE_EQ": return {"instrument_type": "EQUITY", "exchange": "NSE", "trading_symbol": symbol}
        if segment == "BSE_EQ": return {"instrument_type": "EQUITY", "exchange": "BSE", "trading_symbol": symbol}
        if segment == "NSE_INDEX": return {"instrument_type": "INDEX", "exchange": "NSE", "trading_symbol": symbol}
        if segment == "BSE_INDEX": return {"instrument_type": "INDEX", "exchange": "BSE", "trading_symbol": symbol}
        return None

    @staticmethod
    def _segment_exchange(segment: str) -> str:
        return {"NSE_EQ": "NSE", "BSE_EQ": "BSE", "NSE_INDEX": "NSE", "BSE_INDEX": "BSE", "NSE_FO": "NSE", "BSE_FO": "BSE", "MCX_FO": "MCX", "NSE_COM": "NSE", "NCD_FO": "NSE", "BCD_FO": "BSE"}.get(segment, "")

    @staticmethod
    def _format_expiry(expiry_value: Any) -> Optional[str]:
        if expiry_value in (None, ""): return None
        try:
            ts = pd.Timestamp(expiry_value, unit="ms", tz=IST)
            return ts.strftime("%d%b%y").upper()
        except Exception:
            return None

    def _on_candle_complete(self, symbol: str, candle: dict) -> None:
        try:
            self._candle_queue.put_nowait((symbol, candle))
        except queue.Full:
            try:
                self._candle_queue.get_nowait()
                self._candle_queue.put_nowait((symbol, candle))
                logger.warning(f"[LiveBotEngine] Candle queue full for {symbol} — dropped oldest item.")
            except queue.Empty:
                pass
                
    def _on_tick(self, tick) -> None:
        live_state.update_tick(tick.symbol, tick)
        candle = candle_registry.on_tick(tick.symbol, tick)
        if candle:
            self._on_candle_complete(tick.symbol, candle.to_dict())

    def _on_portfolio_update(self, update) -> None:
        pass

    def _strategy_loop(self) -> None:
        logger.info("[StrategyThread] Started.")
        while not self._stop_event.is_set():
            try:
                symbol, candle = self._candle_queue.get(timeout=1.0)
                self._evaluate_strategy(symbol)
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"[StrategyThread] Error evaluating strategy: {e}", exc_info=True)
            self._check_all_sl_tp()
        logger.info("[StrategyThread] Stopped.")

    def _evaluate_strategy(self, symbol: str) -> None:
        cfg = self._config
        
        # I4. Add staleness guard
        if live_state.is_feed_stale(symbol, cfg.stale_tick_threshold_seconds):
            logger.warning(f"[StrategyThread] {symbol} feed is stale. Skipping strategy evaluation.")
            return

        df = candle_registry.get_df(symbol)
        if df.empty or len(df) < cfg.min_bars_required:
            return

        try:
            # I3. Fix double-copy in _evaluate_strategy()
            # Pass df directly to generate_signals, which internally prepares and copies
            df = self._strategy.generate_signals(df)
        except Exception as e:
            logger.error(f"[StrategyThread] generate_signals() error for {symbol}: {e}")
            return

        if "signal" not in df.columns:
            return

        last = df.iloc[-1]
        signal_value = int(last.get("signal", 0)) if not pd.isna(last.get("signal", 0)) else 0
        signal_tag   = str(last.get("signal_tag", self._strategy.__class__.__name__))

        tick = live_state.get_tick(symbol)
        if tick is None:
            return

        ltp = tick.ltp
        instrument_key = tick.instrument_key

        sl_val = last.get("stop_loss") or last.get("signal_sl", 0)
        tp_val = last.get("take_profit") or last.get("signal_tp", 0)
        stop_loss   = float(sl_val) if sl_val else None
        take_profit = float(tp_val) if tp_val else None

        if stop_loss is None and signal_value == 1:
            stop_loss = round(ltp * 0.98, 2)

        if signal_value == 1 and not live_state.has_position(symbol):
            qty = self._risk.compute_position_size(ltp, stop_loss)
            res = self._risk.check_order(symbol, "BUY", qty, ltp, live_state.cash, live_state.get_all_positions())
            if res.allowed:
                self._broker.place_order(symbol=symbol, instrument_key=instrument_key, action="BUY", quantity=qty, order_type="MARKET", stop_loss=stop_loss, take_profit=take_profit, strategy_tag=signal_tag)
                logger.info(f"[Risk/Audit] {symbol} BUY Placed | Tag: {signal_tag} | Reason: {res.reason}")
            else:
                logger.info(f"[StrategyThread] {symbol} BUY blocked: {res.reason}")
        elif signal_value == -1 and live_state.has_position(symbol):
            position = live_state.get_position(symbol)
            if position and position.direction > 0:
                res = self._risk.check_order(symbol, "SELL", position.quantity, ltp, live_state.cash, live_state.get_all_positions())
                if res.allowed:
                    self._broker.place_order(symbol=symbol, instrument_key=instrument_key, action="SELL", quantity=position.quantity, order_type="MARKET", strategy_tag=signal_tag)
                    logger.info(f"[Risk/Audit] {symbol} SELL Placed | Tag: {signal_tag} | Reason: {res.reason}")
                else:
                    logger.warning(f"[StrategyThread] {symbol} SELL blocked: {res.reason}")
        elif signal_value == -1 and not live_state.has_position(symbol):
            # I5. Fix signal direction logging
            if cfg.allow_short:
                qty = self._risk.compute_position_size(ltp, stop_loss)
                res = self._risk.check_order(symbol, "SHORT", qty, ltp, live_state.cash, live_state.get_all_positions())
                if res.allowed:
                    self._broker.place_order(symbol=symbol, instrument_key=instrument_key, action="SHORT", quantity=qty, order_type="MARKET", stop_loss=stop_loss, take_profit=take_profit, strategy_tag=signal_tag)
                    logger.info(f"[Risk/Audit] {symbol} SHORT Placed | Tag: {signal_tag} | Reason: {res.reason}")
                else:
                    logger.warning(f"[StrategyThread] {symbol} SHORT blocked: {res.reason}")
            else:
                logger.info(f"[StrategyThread] {symbol} Bearish signal ignored: allow_short is False")

    def _check_all_sl_tp(self) -> None:
        # I6. Replace _check_all_sl_tp() with targeted check
        for symbol, position in live_state.get_all_positions().items():
            if position.stop_loss or position.take_profit:
                try:
                    self._broker.check_stop_loss_take_profit(symbol)
                except Exception as e:
                    logger.error(f"[StrategyThread] SL/TP check error for {symbol}: {e}")
            try:
                if hasattr(self._broker, "check_pending_limit_orders"):
                    self._broker.check_pending_limit_orders(symbol)
            except Exception as e:
                logger.error(f"[StrategyThread] Pending order check error for {symbol}: {e}")

    def _squareoff_monitor(self) -> None:
        logger.info("[SquareoffThread] Monitor started.")
        while not self._stop_event.is_set():
            try:
                if self._risk.should_squareoff_now():
                    logger.info("[SquareoffThread] 15:20 reached — squaring off all positions.")
                    live_state.log_activity("SQUAREOFF", "⏰ 15:20 IST reached. Squaring off all intraday positions.", level="WARNING")
                    self._broker.squareoff_all()
            except Exception as e:
                logger.error(f"[SquareoffThread] Error: {e}")
            time.sleep(30)
        logger.info("[SquareoffThread] Stopped.")

    def _on_order_update(self, order_data: dict) -> None:
        logger.debug(f"[LiveBotEngine] Portfolio order update: {order_data}")

    @property
    def is_running(self) -> bool:
        return live_state._is_running
