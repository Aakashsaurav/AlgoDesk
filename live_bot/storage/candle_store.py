import pandas as pd
import threading
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class CandleStore:
    def __init__(self, base_dir: Path, session_date: str):
        self.base_dir = base_dir
        self.session_date = session_date
        self._buffers: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def append(self, symbol: str, candle_dict: dict):
        with self._lock:
            if symbol not in self._buffers:
                self._buffers[symbol] = []
            self._buffers[symbol].append(candle_dict)

    def flush(self):
        with self._lock:
            for symbol, buffer in self._buffers.items():
                if not buffer:
                    continue
                
                symbol_dir = self.base_dir / symbol
                symbol_dir.mkdir(parents=True, exist_ok=True)
                filepath = symbol_dir / f"candles_{self.session_date}.parquet"
                
                df_new = pd.DataFrame(buffer)
                buffer.clear()
                
                if filepath.exists():
                    try:
                        df_existing = pd.read_parquet(filepath)
                        df_merged = pd.concat([df_existing, df_new], ignore_index=True)
                    except Exception as e:
                        logger.error(f"Error reading existing candle parquet {filepath}: {e}")
                        df_merged = df_new
                else:
                    df_merged = df_new
                    
                df_merged.drop_duplicates(subset=["datetime"], keep="last", inplace=True)
                df_merged.to_parquet(filepath, index=False)

    def get_candles(self, symbol: str, from_ts, to_ts) -> pd.DataFrame:
        filepath = self.base_dir / symbol / f"candles_{self.session_date}.parquet"
        if filepath.exists():
            df = pd.read_parquet(filepath)
            return df[(df["datetime"] >= from_ts) & (df["datetime"] <= to_ts)]
        return pd.DataFrame()
