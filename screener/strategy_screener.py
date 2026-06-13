"""
Strategy-based screener module for the current R3 screener package.

This module preserves the useful phase-4 screener features while keeping the
implementation aligned with the phase-5 `screener` package style.

Key capabilities:
  - Parallel, multi-symbol scans using a strategy's generate_signals()
  - Configurable pre-filters: min volume, min/max price, min ATR, min bars
  - Multi-strategy scan support and confluence detection
  - CSV + JSON result export for dashboard or later analysis
  - Console-friendly table printing
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from indicators.volatility import atr as compute_atr

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class StrategyScreenerConfig:
    min_volume:      float = 100_000
    min_price:       float = 10.0
    max_price:       float = 0.0
    min_atr_pct:     float = 0.0
    min_bars:        int   = 100
    signal_type:     int   = 1
    max_results:     int   = 50
    rank_by:         str   = "close"
    rank_ascending:  bool  = True
    save_results:    bool  = True
    label:           str  = "screener"
    n_workers:       int  = 8


class StrategyScreener:
    def __init__(self, config: Optional[StrategyScreenerConfig] = None) -> None:
        self.config = config or StrategyScreenerConfig()

    def scan(
        self,
        data_dict: Dict[str, pd.DataFrame],
        strategy: Any,
        extra_filters: Optional[List[Callable[[str, pd.DataFrame, pd.DataFrame], bool]]] = None,
    ) -> List[Dict[str, Any]]:
        cfg = self.config
        symbols = list(data_dict.keys())
        hits: List[Dict[str, Any]] = []
        errors: List[str] = []
        t_start = time.time()

        logger.info(
            f"StrategyScreener: scanning {len(symbols)} symbols | "
            f"signal={cfg.signal_type} | workers={cfg.n_workers}"
        )

        def _process(symbol: str) -> Optional[Dict[str, Any]]:
            try:
                df = data_dict[symbol]
                if df is None or len(df) < cfg.min_bars:
                    return None

                last = df.iloc[-1]
                close = float(last.get("close", 0))
                volume = float(df["volume"].tail(20).mean())

                if close < cfg.min_price:
                    return None
                if cfg.max_price > 0 and close > cfg.max_price:
                    return None
                if volume < cfg.min_volume:
                    return None

                if cfg.min_atr_pct > 0:
                    atr_series = compute_atr(df, 14)
                    atr_value = float(atr_series.iloc[-1])
                    if not np.isnan(atr_value) and (atr_value / close * 100) < cfg.min_atr_pct:
                        return None

                signal_df = strategy.generate_signals(df.copy())
                if "signal" not in signal_df.columns:
                    return None

                last_signal = int(signal_df["signal"].iloc[-1])
                if cfg.signal_type != 0:
                    if last_signal != cfg.signal_type:
                        return None
                elif last_signal == 0:
                    return None

                if extra_filters:
                    for filt in extra_filters:
                        if not filt(symbol, df, signal_df):
                            return None

                row: Dict[str, Any] = {
                    "symbol":    symbol,
                    "signal":    last_signal,
                    "close":     round(close, 2),
                    "volume":    int(volume),
                    "scan_date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
                }

                indicator_cols = [
                    c for c in signal_df.columns
                    if c not in ("open", "high", "low", "close", "volume", "oi", "signal")
                ]
                for col in indicator_cols:
                    val = signal_df[col].iloc[-1]
                    if isinstance(val, (np.floating, float)):
                        row[col] = round(float(val), 4) if not np.isnan(val) else None
                    elif isinstance(val, (np.integer, int)):
                        row[col] = int(val)
                    else:
                        row[col] = val

                return row
            except Exception as exc:
                logger.debug(f"StrategyScreener: symbol={symbol} error={exc}")
                errors.append(symbol)
                return None

        with ThreadPoolExecutor(max_workers=cfg.n_workers) as executor:
            futures = {executor.submit(_process, s): s for s in symbols}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    hits.append(result)

        if hits and cfg.rank_by in hits[0]:
            hits.sort(
                key=lambda row: row.get(cfg.rank_by, 0) or 0,
                reverse=not cfg.rank_ascending,
            )
        else:
            hits.sort(key=lambda row: row.get("close", 0), reverse=not cfg.rank_ascending)

        hits = hits[: cfg.max_results]
        elapsed = time.time() - t_start

        logger.info(
            f"StrategyScreener done: {len(hits)} hits / {len(symbols)} symbols "
            f"in {elapsed:.1f}s | {len(errors)} errors"
        )

        if cfg.save_results:
            self._save_results(hits, strategy)

        return hits

    def scan_parallel(
        self,
        data_dict: Dict[str, pd.DataFrame],
        strategies: List[Any],
        labels: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        results: Dict[str, List[Dict[str, Any]]] = {}
        for idx, strategy in enumerate(strategies):
            label = (labels[idx] if labels and idx < len(labels)
                     else getattr(strategy, "name", f"strategy_{idx}"))
            logger.info(f"StrategyScreener: multi-strategy scan {label}")
            previous_label = self.config.label
            self.config.label = label
            results[label] = self.scan(data_dict, strategy)
            self.config.label = previous_label
        return results

    def confluence(
        self,
        multi_results: Dict[str, List[Dict[str, Any]]],
        min_count: int = 2,
    ) -> List[Dict[str, Any]]:
        from collections import Counter

        all_symbols: List[str] = []
        for strategy_name, hits in multi_results.items():
            all_symbols.extend([hit["symbol"] for hit in hits])

        counts = Counter(all_symbols)
        confirmed: List[Dict[str, Any]] = []
        for symbol, count in counts.items():
            if count >= min_count:
                strategies = [
                    name for name, hits in multi_results.items()
                    if any(hit["symbol"] == symbol for hit in hits)
                ]
                confirmed.append({
                    "symbol": symbol,
                    "strategy_count": count,
                    "strategies": strategies,
                })

        confirmed.sort(key=lambda row: row["strategy_count"], reverse=True)
        logger.info(
            f"StrategyScreener confluence: {len(confirmed)} symbols confirmed by {min_count}+ strategies"
        )
        return confirmed

    def _save_results(self, hits: List[Dict[str, Any]], strategy: Any) -> None:
        if not hits:
            logger.info("StrategyScreener: no hits to save")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        label = f"{self.config.label}_{timestamp}"

        csv_path = OUTPUT_DIR / f"{label}.csv"
        pd.DataFrame(hits).to_csv(csv_path, index=False)
        logger.info(f"StrategyScreener CSV saved → {csv_path}")

        json_path = OUTPUT_DIR / f"{label}.json"
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(
                {
                    "scan_time": timestamp,
                    "strategy": getattr(strategy, "name", type(strategy).__name__),
                    "signal_type": self.config.signal_type,
                    "total_hits": len(hits),
                    "results": hits,
                },
                json_file,
                indent=2,
                default=str,
            )
        logger.info(f"StrategyScreener JSON saved → {json_path}")

    def print_results(self, hits: List[Dict[str, Any]], max_cols: int = 8) -> None:
        if not hits:
            print("No signals found.")
            return

        df = pd.DataFrame(hits)
        cols = list(df.columns[:max_cols])
        display_df = df[cols].copy()

        for col in display_df.select_dtypes(include=[float]).columns:
            display_df[col] = display_df[col].map(lambda x: f"{x:.2f}" if x is not None else "N/A")

        print("\n" + "=" * 80)
        print(f"  STRATEGY SCREENER RESULTS — {len(hits)} signals")
        print("=" * 80)
        print(display_df.to_string(index=False))
        print("=" * 80)
