import pandas as pd
import threading
import time
from pathlib import Path
from live_bot.models import TickData
import logging

logger = logging.getLogger(__name__)

class TickStore:
    MAX_BUFFER_SIZE = 1000
    MAX_BUFFER_AGE_SECONDS = 5.0

    def __init__(self, base_dir: Path, session_date: str, symbol: str):
        self.base_dir = base_dir
        self.session_date = session_date
        self.symbol = symbol
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._last_flush_time = time.monotonic()
        
        self.symbol_dir = self.base_dir / self.symbol
        self.symbol_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.symbol_dir / f"{self.session_date}.parquet"

    def append(self, tick: TickData) -> None:
        row = {
            "timestamp": tick.received_at,
            "instrument_key": tick.instrument_key,
            "symbol": tick.symbol,
            "ltp": tick.ltp,
            "ltt": tick.ltt,
            "ltq": tick.ltpc.ltq,
            "close_price": tick.ltpc.close_price,
            "volume": tick.atp or 0,  # Just placeholder logic
            "oi": tick.oi or 0.0,
            "bid_price_1": tick.depth_5[0].bid_price if tick.depth_5 else 0.0,
            "ask_price_1": tick.depth_5[0].ask_price if tick.depth_5 else 0.0,
            "feed_mode": tick.feed_mode.value,
            "feed_source": tick.feed_source.value,
        }
        
        with self._lock:
            self._buffer.append(row)
            should_flush = (
                len(self._buffer) >= self.MAX_BUFFER_SIZE or
                (time.monotonic() - self._last_flush_time) >= self.MAX_BUFFER_AGE_SECONDS
            )
            
        if should_flush:
            self.flush()

    def flush(self) -> Path | None:
        with self._lock:
            if not self._buffer:
                return None
            df_new = pd.DataFrame(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.monotonic()
            
        # Merge-and-rewrite
        if self.filepath.exists():
            try:
                df_existing = pd.read_parquet(self.filepath)
                df_merged = pd.concat([df_existing, df_new], ignore_index=True)
            except Exception as e:
                logger.error(f"Error reading existing parquet {self.filepath}: {e}")
                df_merged = df_new
        else:
            df_merged = df_new
            
        df_merged.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
        df_merged.to_parquet(self.filepath, index=False)
        return self.filepath

    def close(self):
        self.flush()

    def get_today_ticks(self, symbol: str) -> pd.DataFrame:
        if self.filepath.exists():
            return pd.read_parquet(self.filepath)
        return pd.DataFrame()

    def get_ticks(self, symbol: str, from_ts, to_ts) -> pd.DataFrame:
        df = self.get_today_ticks(symbol)
        if df.empty:
            return df
        return df[(df["timestamp"] >= from_ts) & (df["timestamp"] <= to_ts)]


class TickStoreManager:
    def __init__(self, base_dir: Path, session_date: str):
        self.base_dir = base_dir
        self.session_date = session_date
        self.stores: dict[str, TickStore] = {}
        self._lock = threading.Lock()

    def get_store(self, symbol: str) -> TickStore:
        with self._lock:
            if symbol not in self.stores:
                self.stores[symbol] = TickStore(self.base_dir, self.session_date, symbol)
            return self.stores[symbol]

    def record_tick(self, tick: TickData):
        store = self.get_store(tick.symbol)
        store.append(tick)

    def record_candle(self, symbol: str, candle: dict):
        # Implementation depends on candle store
        pass

    def flush_all(self):
        with self._lock:
            for store in self.stores.values():
                store.flush()

    def close_all(self):
        with self._lock:
            for store in self.stores.values():
                store.close()
