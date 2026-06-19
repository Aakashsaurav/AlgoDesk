"""
live_bot/state.py
-----------------
Shared, thread-safe in-memory state for the live trading engine.
"""

import threading
import logging
from collections import deque
from datetime import datetime, date
from typing import Deque, Dict, List, Optional
from notifications.dispatcher import notify
from config import IST

# Import the refactored data models
from live_bot.models import TickData, LivePosition, LiveOrder, ClosedTrade, SessionStats, FeedMode

logger = logging.getLogger(__name__)

class LiveState:
    def __init__(self):
        self._lock = threading.RLock()

        # ── Market Data ───────────────────────────────────────────────────────
        self._ticks:          Dict[str, TickData]     = {}
        self._tick_history:   Dict[str, Deque[TickData]] = {}
        self._last_tick_received: Dict[str, datetime] = {}

        # ── Portfolio ─────────────────────────────────────────────────────────
        self._positions:      Dict[str, LivePosition] = {}
        self._open_orders:    Dict[str, LiveOrder]    = {}
        self._closed_trades:  List[ClosedTrade]       = []

        # ── Capital tracking ──────────────────────────────────────────────────
        self._initial_capital:   float = 500_000.0
        self._cash:              float = 500_000.0
        self._peak_capital:      float = 500_000.0
        
        # ── Day stats ─────────────────────────────────────────────────────────
        self._day_pnl:           float = 0.0
        self._day_start_capital: float = 500_000.0
        self._day_start_date:    Optional[date] = None

        # ── Risk flags ────────────────────────────────────────────────────────
        self._kill_switch:    bool = False
        self._daily_loss_hit: bool = False
        self._max_dd_hit:     bool = False

        # ── Engine status ─────────────────────────────────────────────────────
        self._is_running:              bool  = False
        self._market_feed_connected:   bool  = False
        self._portfolio_feed_connected:bool  = False
        self._subscribed_symbols:      List[str] = []
        self._active_strategy:         Optional[str] = None
        self._bot_start_time:          Optional[datetime] = None

        self._activity_log: Deque[dict] = deque(maxlen=200)

        # Session tracking counters
        self._ticks_received_count = 0
        self._candles_completed_count = 0
        self._orders_placed_count = 0
        self._ws_disconnects = 0
        self._rest_activations = 0

        logger.info("LiveState initialised.")

    def reset_daily_state(self):
        """Reset state at the start of a new trading session."""
        with self._lock:
            self._day_pnl = 0.0
            self._daily_loss_hit = False
            self._max_dd_hit = False
            self._day_start_capital = self.total_value
            self._day_start_date = date.today()
            self._peak_capital = self.total_value
            
            # Reset counters
            self._ticks_received_count = 0
            self._candles_completed_count = 0
            self._orders_placed_count = 0
            self._ws_disconnects = 0
            self._rest_activations = 0

            self._log_activity("SYSTEM", "Daily state reset completed.")

    # ─── Tick data ────────────────────────────────────────────────────────────

    def update_tick(self, symbol: str, tick: TickData) -> None:
        with self._lock:
            self._ticks[symbol] = tick
            self._last_tick_received[symbol] = datetime.now(tz=IST)
            self._ticks_received_count += 1
            
            if symbol not in self._tick_history:
                self._tick_history[symbol] = deque(maxlen=500)
            self._tick_history[symbol].append(tick)

    def is_feed_stale(self, symbol: str, max_age_seconds: float = 5.0) -> bool:
        with self._lock:
            last_ts = self._last_tick_received.get(symbol)
            if not last_ts:
                return True
            return (datetime.now(tz=IST) - last_ts).total_seconds() > max_age_seconds

    def is_any_feed_stale(self, max_age_seconds: float = 5.0) -> bool:
        with self._lock:
            if not self._subscribed_symbols:
                return False
            for sym in self._subscribed_symbols:
                if self.is_feed_stale(sym, max_age_seconds):
                    return True
            return False

    def get_stale_symbols(self, max_age_seconds: float = 5.0) -> list[str]:
        with self._lock:
            stale = []
            for sym in self._subscribed_symbols:
                if self.is_feed_stale(sym, max_age_seconds):
                    stale.append(sym)
            return stale

    def get_tick(self, symbol: str) -> Optional[TickData]:
        with self._lock:
            return self._ticks.get(symbol)

    def get_all_ticks(self) -> Dict[str, TickData]:
        with self._lock:
            return dict(self._ticks)

    def get_all_ticks_snapshot(self) -> dict:
        """Returns dict of all ticks as serialisable dicts."""
        with self._lock:
            return {
                sym: {
                    "ltp": tick.ltp,
                    "ltt": tick.ltt.isoformat(),
                    "ltq": tick.ltpc.ltq,
                    "close_price": tick.ltpc.close_price,
                    "feed_mode": tick.feed_mode.value,
                    "feed_source": tick.feed_source.value,
                }
                for sym, tick in self._ticks.items()
            }

    def get_tick_history(self, symbol: str) -> List[TickData]:
        with self._lock:
            return list(self._tick_history.get(symbol, []))

    # ─── Positions ────────────────────────────────────────────────────────────

    def add_position(self, position: LivePosition) -> None:
        with self._lock:
            if position.symbol in self._positions:
                logger.warning("Position for %s already exists — overwriting.", position.symbol)
            self._positions[position.symbol] = position
            logger.info("Position opened: %s %s x%d @ ₹%.2f",
                position.symbol, "LONG" if position.direction > 0 else "SHORT",
                position.quantity, position.entry_price)

    def close_position(self, symbol: str) -> Optional[LivePosition]:
        with self._lock:
            return self._positions.pop(symbol, None)

    def get_position(self, symbol: str) -> Optional[LivePosition]:
        with self._lock:
            return self._positions.get(symbol)

    def get_all_positions(self) -> Dict[str, LivePosition]:
        with self._lock:
            return dict(self._positions)

    def has_position(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._positions

    # ─── Orders ───────────────────────────────────────────────────────────────

    def add_order(self, order: LiveOrder) -> None:
        with self._lock:
            self._open_orders[order.order_id] = order
            self._orders_placed_count += 1

    def update_order_status(
        self, order_id: str, status: str, fill_price: Optional[float] = None, filled_at: Optional[datetime] = None,
    ) -> Optional[LiveOrder]:
        with self._lock:
            order = self._open_orders.get(order_id)
            if not order:
                return None
            order.status = status
            if fill_price is not None:
                order.fill_price = fill_price
            if filled_at is not None:
                order.filled_at = filled_at
            return order

    def get_order(self, order_id: str) -> Optional[LiveOrder]:
        with self._lock:
            return self._open_orders.get(order_id)

    def get_all_orders(self) -> Dict[str, LiveOrder]:
        with self._lock:
            return dict(self._open_orders)

    # ─── Closed Trades ────────────────────────────────────────────────────────

    def record_closed_trade(self, trade: ClosedTrade) -> None:
        with self._lock:
            self._closed_trades.append(trade)
            self._day_pnl += trade.pnl
            logger.info("Trade closed: %s %s P&L=₹%.2f", trade.symbol, trade.direction, trade.pnl)

    def get_closed_trades(self) -> List[ClosedTrade]:
        with self._lock:
            return list(self._closed_trades)

    # ─── Capital ──────────────────────────────────────────────────────────────

    def set_initial_capital(self, amount: float) -> None:
        with self._lock:
            self._initial_capital    = amount
            self._cash               = amount
            self._peak_capital       = amount
            self._day_start_capital  = amount
            self._day_start_date     = date.today()

    def debit_cash(self, amount: float) -> None:
        with self._lock:
            if amount > self._cash:
                raise ValueError(f"Insufficient cash: need ₹{amount:.2f}, have ₹{self._cash:.2f}")
            self._cash -= amount

    def credit_cash(self, amount: float) -> None:
        with self._lock:
            self._cash += amount
            if self._cash > self._peak_capital:
                self._peak_capital = self._cash

    @property
    def cash(self) -> float:
        with self._lock:
            return self._cash

    @property
    def total_value(self) -> float:
        """Cash + unrealised P&L of all open positions. Inline computation to avoid locks."""
        with self._lock:
            total = self._cash
            for sym, pos in self._positions.items():
                tick = self._ticks.get(sym)
                if tick and tick.ltp > 0:
                    total += (tick.ltp - pos.entry_price) * pos.quantity * pos.direction
            return total

    @property
    def day_pnl(self) -> float:
        with self._lock:
            return self._day_pnl

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown from peak as percentage (0-100)."""
        with self._lock:
            if self._peak_capital <= 0:
                return 0.0
            
            # Inline total_value calculation
            total = self._cash
            for sym, pos in self._positions.items():
                tick = self._ticks.get(sym)
                if tick and tick.ltp > 0:
                    total += (tick.ltp - pos.entry_price) * pos.quantity * pos.direction
            
            return max(0.0, (self._peak_capital - total) / self._peak_capital * 100)

    # ─── Risk flags ───────────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "") -> None:
        with self._lock:
            self._kill_switch = True
            msg = f"🔴 KILL SWITCH ACTIVATED{f': {reason}' if reason else ''}"
            logger.critical(msg)
            self._log_activity("KILL_SWITCH", msg, level="CRITICAL")
            notify("KILL_SWITCH", "KILL SWITCH ACTIVATED", msg, priority="CRITICAL")

    def set_daily_loss_hit(self) -> None:
        with self._lock:
            self._daily_loss_hit = True
            msg = "⚠️ Daily loss limit reached."
            logger.warning(msg)
            self._log_activity("RISK_ALERT", msg, level="WARNING")
            notify("RISK_ALERT", "Risk Alert", msg, priority="WARNING")

    def set_max_dd_hit(self) -> None:
        with self._lock:
            self._max_dd_hit = True

    @property
    def kill_switch(self) -> bool:
        with self._lock:
            return self._kill_switch

    def is_trading_allowed(self) -> bool:
        with self._lock:
            return (
                self._is_running
                and not self._kill_switch
                and not self._daily_loss_hit
                and not self._max_dd_hit
                and self._market_feed_connected
                and not self.is_any_feed_stale()
            )

    # ─── Engine status ────────────────────────────────────────────────────────

    def set_running(self, val: bool) -> None:
        with self._lock:
            self._is_running = val
            if val:
                self._bot_start_time = datetime.now()

    def set_market_feed_status(self, connected: bool) -> None:
        with self._lock:
            self._market_feed_connected = connected

    def set_portfolio_feed_status(self, connected: bool) -> None:
        with self._lock:
            self._portfolio_feed_connected = connected

    def set_subscribed_symbols(self, symbols: List[str]) -> None:
        with self._lock:
            self._subscribed_symbols = list(symbols)

    def set_active_strategy(self, name: Optional[str]) -> None:
        with self._lock:
            self._active_strategy = name

    def get_status_snapshot(self) -> dict:
        with self._lock:
            # Inline total_value to avoid lock contention
            total = self._cash
            positions_data = {}
            for sym, pos in self._positions.items():
                tick = self._ticks.get(sym)
                ltp  = tick.ltp if tick else pos.entry_price
                unreal_pnl = (ltp - pos.entry_price) * pos.quantity * pos.direction
                total += unreal_pnl
                
                positions_data[sym] = {
                    "direction":      "LONG" if pos.direction > 0 else "SHORT",
                    "quantity":       pos.quantity,
                    "entry_price":    round(pos.entry_price, 2),
                    "ltp":            round(ltp, 2),
                    "unrealised_pnl": round(unreal_pnl, 2),
                    "stop_loss":      pos.stop_loss,
                    "take_profit":    pos.take_profit,
                    "strategy_tag":   pos.strategy_tag,
                    "entry_time":     pos.entry_time.isoformat(),
                }

            if self._peak_capital <= 0:
                dd_pct = 0.0
            else:
                dd_pct = max(0.0, (self._peak_capital - total) / self._peak_capital * 100)

            return {
                "is_running":                self._is_running,
                "market_feed_connected":     self._market_feed_connected,
                "portfolio_feed_connected":  self._portfolio_feed_connected,
                "kill_switch":               self._kill_switch,
                "daily_loss_hit":            self._daily_loss_hit,
                "is_trading_allowed":        self.is_trading_allowed(),
                "active_strategy":           self._active_strategy,
                "subscribed_symbols":        self._subscribed_symbols,
                "cash":                      round(self._cash, 2),
                "total_value":               round(total, 2),
                "day_pnl":                   round(self._day_pnl, 2),
                "drawdown_pct":              round(dd_pct, 2),
                "initial_capital":           round(self._initial_capital, 2),
                "open_positions":            positions_data,
                "market_ticks":              self.get_all_ticks_snapshot(),
                "closed_trades":             [],  # serialize trades if needed
                "activity_log":              list(self._activity_log),
                "bot_start_time":            self._bot_start_time.isoformat() if self._bot_start_time else None,
            }

    def get_session_stats(self) -> SessionStats:
        with self._lock:
            return SessionStats(
                session_date=date.today().isoformat(),
                symbols_subscribed=list(self._subscribed_symbols),
                feed_mode=FeedMode.FULL, # fallback representation
                ticks_received=self._ticks_received_count,
                candles_completed=self._candles_completed_count,
                orders_placed=self._orders_placed_count,
                websocket_disconnects=self._ws_disconnects,
                rest_fallback_activations=self._rest_activations,
                started_at=self._bot_start_time or datetime.now(tz=IST),
                ended_at=None
            )

    def increment_candle_completed(self):
        with self._lock:
            self._candles_completed_count += 1

    def increment_ws_disconnect(self):
        with self._lock:
            self._ws_disconnects += 1

    def increment_rest_activation(self):
        with self._lock:
            self._rest_activations += 1

    # ─── Activity log ─────────────────────────────────────────────────────────

    def get_activity_log(self, last_n: int = 200) -> List[dict]:
        with self._lock:
            entries = list(self._activity_log)
        return entries[-last_n:]

    def get_status_dict(self) -> dict:
        return self.get_status_snapshot()

    def log_activity(self, event_type: str, message: str, level: str = "INFO") -> None:
        with self._lock:
            self._log_activity(event_type, message, level)

    def _log_activity(self, event_type: str, message: str, level: str = "INFO") -> None:
        entry = {
            "time":       datetime.now().isoformat(),
            "event_type": event_type,
            "message":    message,
            "level":      level,
        }
        self._activity_log.append(entry)


# ── Module-level singleton ────────────────────────────────────────────────────
state = LiveState()