import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from screener.base import TickData

class DataValidator:
    """Validates data structures before processing."""

    @staticmethod
    def validate(symbol: str, df: pd.DataFrame) -> tuple[bool, str]:
        if df is None or df.empty:
            return False, f"{symbol}: DataFrame is empty"
        
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return False, f"{symbol}: Missing required columns {missing_cols}"
            
        if not isinstance(df.index, pd.DatetimeIndex):
            return False, f"{symbol}: Index must be a DatetimeIndex"
            
        # Check if any row has all NaNs in the required columns
        if df[required_cols].isna().all(axis=1).any():
            return False, f"{symbol}: Contains rows with all NaN values in OHLCV columns"
            
        return True, ""

    @staticmethod
    def validate_tick(symbol: str, tick: TickData) -> tuple[bool, str]:
        if tick is None:
            return False, f"{symbol}: TickData is None"
        if tick.symbol != symbol:
            return False, f"{symbol}: TickData symbol {tick.symbol} does not match {symbol}"
        if not tick.validate():
            return False, f"{symbol}: TickData is invalid"
        return True, ""


@dataclass
class PreFilter:
    """Filters out instruments before running heavy indicator logic."""
    min_bars: int = 50
    min_price: float = 0.0
    max_price: float = 0.0
    min_volume: float = 0.0
    min_atr_pct: float = 0.0
    required_columns: list[str] = field(default_factory=lambda: ["open", "high", "low", "close", "volume"])

    def apply(self, symbol: str, df: pd.DataFrame) -> tuple[bool, str]:
        missing_cols = [c for c in self.required_columns if c not in df.columns]
        if missing_cols:
            return False, f"Missing required columns {missing_cols}"
            
        if len(df) < self.min_bars:
            return False, f"Insufficient bars: {len(df)} < {self.min_bars}"
            
        last_row = df.iloc[-1]
        close_price = float(last_row["close"])
        volume = float(last_row["volume"])
        
        if self.min_price > 0 and close_price < self.min_price:
            return False, f"Price below minimum: {close_price} < {self.min_price}"
            
        if self.max_price > 0 and close_price > self.max_price:
            return False, f"Price above maximum: {close_price} > {self.max_price}"
            
        if self.min_volume > 0 and volume < self.min_volume:
            return False, f"Volume below minimum: {volume} < {self.min_volume}"
            
        if self.min_atr_pct > 0:
            if len(df) >= 14:
                high = df["high"].to_numpy()
                low = df["low"].to_numpy()
                close = df["close"].to_numpy()
                
                prev_close = np.roll(close, 1)
                prev_close[0] = close[0]
                
                tr1 = high - low
                tr2 = np.abs(high - prev_close)
                tr3 = np.abs(low - prev_close)
                tr = np.maximum(tr1, np.maximum(tr2, tr3))
                
                atr = pd.Series(tr).rolling(window=14).mean().iloc[-1]
                
                if pd.notna(atr) and close_price > 0:
                    atr_pct = (atr / close_price) * 100
                    if atr_pct < self.min_atr_pct:
                        return False, f"ATR % below minimum: {atr_pct:.2f} < {self.min_atr_pct}"
            else:
                return False, f"Not enough bars for ATR calculation: {len(df)} < 14"
                
        return True, ""

    def apply_tick(self, symbol: str, tick: TickData) -> tuple[bool, str]:
        if self.min_price > 0 and tick.ltp < self.min_price:
            return False, f"Tick price below minimum: {tick.ltp} < {self.min_price}"
            
        if self.max_price > 0 and tick.ltp > self.max_price:
            return False, f"Tick price above maximum: {tick.ltp} > {self.max_price}"
            
        if self.min_volume > 0 and tick.volume < self.min_volume:
            return False, f"Tick volume below minimum: {tick.volume} < {self.min_volume}"
            
        return True, ""
