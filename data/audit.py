import sqlite3
import csv
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from config import config, IST_TZ
from live_bot.models import LiveOrder, ClosedTrade

@dataclass
class AuditEntry:
    id: int
    timestamp: str
    event_type: str
    symbol: str
    action: str
    price: float
    reason: str
    result: str

class AuditLogger:
    def __init__(self, db_path: Path = None):
        if db_path is None:
            self.db_path = config.SQLITE_DIR / "audit.db"
        else:
            self.db_path = db_path
            
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    action TEXT,
                    price REAL,
                    reason TEXT,
                    result TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_symbol ON audit_log(symbol)")
            
    def _log(self, event_type: str, symbol: str, action: str, price: float, reason: str, result: str):
        now = datetime.now(tz=IST_TZ).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO audit_log (timestamp, event_type, symbol, action, price, reason, result)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, event_type, symbol, action, price, reason, result))
            
    def log_signal(self, symbol: str, strategy: str, direction: str, reason: str, bar_time: str):
        self._log("SIGNAL", symbol, direction, 0.0, f"Strategy: {strategy}, Reason: {reason}", "GENERATED")
        
    def log_risk_check(self, symbol: str, action: str, result_code: str, reason: str):
        self._log("RISK_CHECK", symbol, action, 0.0, reason, result_code)
        
    def log_order_placed(self, order: LiveOrder):
        self._log("ORDER_PLACED", order.symbol, order.action, order.limit_price or 0.0, "System logic", "PLACED")
        
    def log_order_filled(self, order: LiveOrder, fill_price: float, slippage: float):
        self._log("ORDER_FILLED", order.symbol, order.action, fill_price, f"Slippage: {slippage}", "FILLED")
        
    def log_order_rejected(self, order_id: str, reason: str):
        self._log("ORDER_REJECTED", "UNKNOWN", "UNKNOWN", 0.0, f"Order {order_id}: {reason}", "REJECTED")
        
    def log_position_closed(self, trade: ClosedTrade):
        self._log("POSITION_CLOSED", trade.symbol, trade.direction, trade.exit_price, f"PnL: {trade.pnl}", "CLOSED")
        
    def query(self, from_date: str, to_date: str, symbol: str = None) -> list[AuditEntry]:
        query = "SELECT id, timestamp, event_type, symbol, action, price, reason, result FROM audit_log WHERE timestamp >= ? AND timestamp <= ?"
        params = [from_date, to_date]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
            
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [AuditEntry(**dict(row)) for row in rows]
            
    def export_csv(self, path: Path, from_date: str, to_date: str):
        entries = self.query(from_date, to_date)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Timestamp", "Event", "Symbol", "Action", "Price", "Reason", "Result"])
            for e in entries:
                writer.writerow([e.id, e.timestamp, e.event_type, e.symbol, e.action, e.price, e.reason, e.result])
