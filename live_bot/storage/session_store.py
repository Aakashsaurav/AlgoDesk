import sqlite3
from pathlib import Path
from datetime import datetime
from live_bot.models import SessionStats, LiveOrder, ClosedTrade

class SessionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_date TEXT PRIMARY KEY,
                    symbols_subscribed TEXT,
                    feed_mode TEXT,
                    ticks_received INTEGER,
                    candles_completed INTEGER,
                    orders_placed INTEGER,
                    websocket_disconnects INTEGER,
                    rest_fallback_activations INTEGER,
                    started_at TEXT,
                    ended_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_orders (
                    order_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    action TEXT,
                    quantity INTEGER,
                    status TEXT,
                    created_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS closed_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    direction TEXT,
                    quantity INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    pnl REAL,
                    pnl_pct REAL
                )
            ''')
            conn.commit()

    def save_session(self, stats: SessionStats):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sessions 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stats.session_date,
                ",".join(stats.symbols_subscribed),
                stats.feed_mode.value,
                stats.ticks_received,
                stats.candles_completed,
                stats.orders_placed,
                stats.websocket_disconnects,
                stats.rest_fallback_activations,
                stats.started_at.isoformat() if stats.started_at else None,
                stats.ended_at.isoformat() if stats.ended_at else None
            ))
            conn.commit()

    def get_sessions(self, from_date: str, to_date: str) -> list[SessionStats]:
        # Minimal stub implementation
        return []

    def save_order(self, order: LiveOrder):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO live_orders 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                order.order_id,
                order.symbol,
                order.action,
                order.quantity,
                order.status,
                order.created_at.isoformat()
            ))
            conn.commit()

    def save_trade(self, trade: ClosedTrade):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO closed_trades (symbol, direction, quantity, entry_price, exit_price, pnl, pnl_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.symbol,
                trade.direction,
                trade.quantity,
                trade.entry_price,
                trade.exit_price,
                trade.pnl,
                trade.pnl_pct
            ))
            conn.commit()

    def get_trades(self, from_date: str, to_date: str) -> list[ClosedTrade]:
        # Minimal stub
        return []
