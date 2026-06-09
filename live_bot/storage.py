"""
live_bot/storage.py
--------------------
Use cases:
    1. Persist live market data internally without relying on ad-hoc test scripts.
    2. Save raw feed records, normalised ticks, and completed candles in a
       disk-efficient format suitable for long-running live capture.
    3. Keep storage append-only and chunked so large tick datasets remain manageable.

Storage format:
    Parquet with ZSTD compression.

Why Parquet:
    - Columnar compression is far more space-efficient than CSV/JSONL for
      long-running tick capture.
    - Fast for both archival and later analytics.
    - Appending chunk files avoids expensive read-modify-write cycles.

P2 FIX (2026-04-11) — redundant JSON serialisation in record_raw_message
=========================================================================
The original ``record_raw_message`` called ``_jsonify(message)`` (full
payload, ~2–10 KB) and ``_jsonify(message.get("marketInfo", {}))`` once
*per instrument* inside the inner loop.  With a typical 10-symbol feed at
10 ticks/second:

    10 ticks/s × 10 symbols × 2 redundant serialisations = 200 json.dumps/s

Both values are identical for every instrument in the same message, yet
were serialised N times. The fix hoists them to be computed once per
message and assigned into each row by reference.

Savings scale linearly with instrument count:
    N=1:  0 redundant calls saved per message
    N=10: 18 redundant calls saved per message  (2 × (N−1))
    N=50: 98 redundant calls saved per message
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

import pandas as pd

from config import config

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None

logger = logging.getLogger(__name__)

DATASETS = ("raw", "ticks", "candles")


def _require_pyarrow() -> None:
    if pq is None or pa is None:
        raise RuntimeError("pyarrow is required for live data parquet storage.")


def _safe_symbol(symbol: str) -> str:
    return (symbol or "UNKNOWN").strip().upper().replace("/", "_").replace(" ", "_")


def _jsonify(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (dict, list, tuple)):
        return _jsonify(value)
    return value


class LiveMarketDataStorage:
    """
    Chunked Parquet writer for raw messages, parsed ticks, and completed candles.

    Each dataset is partitioned by symbol/date/hour and flushed in small batches
    to avoid large in-memory buffers or frequent tiny writes.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        flush_size: int = 50,
        flush_interval_seconds: float = 5.0,
        compression: str = "zstd",
        enabled: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir or config.LIVE_TICK_DIR)
        self.flush_size = int(flush_size)
        self.flush_interval_seconds = float(flush_interval_seconds)
        self.compression = compression
        self.enabled = enabled

        self._lock = threading.RLock()
        self._buffers: MutableMapping[str, List[Dict[str, Any]]] = {
            name: [] for name in DATASETS
        }
        self._last_flush_ts = time.time()

    def _dataset_dir(self, dataset: str, symbol: str, event_time: datetime) -> Path:
        event_dt  = pd.Timestamp(event_time)
        date_part = event_dt.strftime("%Y-%m-%d")
        hour_part = event_dt.strftime("%H")
        return self.base_dir / dataset / _safe_symbol(symbol) / date_part / hour_part

    def _write_rows(self, dataset: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        _require_pyarrow()

        grouped: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in rows:
            symbol     = _safe_symbol(str(row.get("symbol", "UNKNOWN")))
            event_time = row.get("event_time")
            if not isinstance(event_time, datetime):
                event_time = pd.Timestamp(row.get("event_time")).to_pydatetime()
            key = (symbol, event_time.strftime("%Y-%m-%d-%H"))
            grouped.setdefault(key, []).append(row)

        for (symbol, _bucket), bucket_rows in grouped.items():
            event_time = bucket_rows[0]["event_time"]
            target_dir = self._dataset_dir(dataset, symbol, event_time)
            target_dir.mkdir(parents=True, exist_ok=True)

            df        = pd.DataFrame(bucket_rows)
            file_path = target_dir / f"{dataset}_{int(time.time() * 1000)}.parquet"
            table     = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, file_path, compression=self.compression)

    def flush(self, datasets: Optional[Iterable[str]] = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            target_datasets = tuple(datasets or DATASETS)
            for dataset in target_datasets:
                rows = self._buffers.get(dataset, [])
                if rows:
                    self._write_rows(dataset, rows)
                    self._buffers[dataset] = []
            self._last_flush_ts = time.time()

    def _append(self, dataset: str, row: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._buffers[dataset].append(row)
            should_flush = (
                len(self._buffers[dataset]) >= self.flush_size
                or (time.time() - self._last_flush_ts) >= self.flush_interval_seconds
            )
        if should_flush:
            self.flush([dataset])

    def record_raw_message(
        self,
        message: Mapping[str, Any],
        instrument_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Persist one WebSocket message as flattened per-instrument raw rows.

        P2 FIX: ``_jsonify(message)`` (full payload) and
        ``_jsonify(message.get("marketInfo", {}))`` are now computed ONCE
        before the per-instrument loop and reused for each row.

        Previously these were called inside the loop, serialising the same
        unchanged dict N times per message (N = number of instruments).
        With 10 symbols at 10 ticks/s that was 200 redundant json.dumps/s.
        """
        if not self.enabled:
            return

        instrument_map = instrument_map or {}
        current_ts = message.get("currentTs")
        event_time = pd.Timestamp.now(tz="UTC").tz_convert("Asia/Kolkata").to_pydatetime()
        if current_ts:
            try:
                if isinstance(current_ts, (int, float)):
                    timestamp = pd.Timestamp(current_ts, unit="ms", tz="UTC")
                else:
                    timestamp = pd.Timestamp(current_ts)
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.tz_localize("UTC")
                    else:
                        timestamp = timestamp.tz_convert("UTC")
                event_time = timestamp.tz_convert("Asia/Kolkata").to_pydatetime()
            except Exception:
                pass

        feeds = message.get("feeds", {})
        if not isinstance(feeds, dict) or not feeds:
            row = {
                "event_time":       event_time,
                "symbol":           "SYSTEM",
                "instrument_key":   "",
                "message_type":     str(message.get("type", "")),
                "current_ts":       current_ts,
                "market_info_json": _jsonify(message.get("marketInfo", {})),
                "payload_json":     _jsonify(dict(message)),
            }
            self._append("raw", row)
            return

        # P2 FIX: serialise once per message, not once per instrument ──────────
        payload_json_str     = _jsonify(dict(message))
        market_info_json_str = _jsonify(message.get("marketInfo", {}))
        message_type_str     = str(message.get("type", ""))
        # ─────────────────────────────────────────────────────────────────────

        for instrument_key, feed_data in feeds.items():
            symbol     = instrument_map.get(instrument_key, instrument_key.split("|")[-1])
            full_feed  = feed_data.get("fullFeed", {})
            market_ff  = full_feed.get("marketFF", {})
            ltpc       = market_ff.get("ltpc", {})
            e_feed     = market_ff.get("eFeedDetails", {})
            market_level = market_ff.get("marketLevel", {})
            market_ohlc  = market_ff.get("marketOHLC", {})

            row = {
                "event_time":        event_time,
                "symbol":            symbol,
                "instrument_key":    instrument_key,
                "message_type":      message_type_str,
                "current_ts":        current_ts,
                "ltp":               float(ltpc.get("ltp", 0) or 0),
                "ltt_ms":            ltpc.get("ltt"),
                "ltq":               int(ltpc.get("ltq", 0) or 0),
                "cp":                float(ltpc.get("cp", 0) or 0),
                "atp":               float(e_feed.get("atp", 0) or 0),
                "open_price":        float(e_feed.get("open", 0) or 0),
                "high_price":        float(e_feed.get("high", 0) or 0),
                "low_price":         float(e_feed.get("low", 0) or 0),
                "close_price":       float(e_feed.get("close", 0) or 0),
                "vtt":               int(e_feed.get("vtt", 0) or 0),
                "oi":                float(e_feed.get("oi", 0) or 0),
                "tbq":               float(e_feed.get("tbq", 0) or 0),
                "tsq":               float(e_feed.get("tsq", 0) or 0),
                "lower_cb":          float(e_feed.get("lowerCP", e_feed.get("lowerCircuit", 0)) or 0),
                "upper_cb":          float(e_feed.get("upperCP", e_feed.get("upperCircuit", 0)) or 0),
                # P2 FIX: reuse pre-serialised strings (no redundant json.dumps)
                "market_info_json":  market_info_json_str,
                "payload_json":      payload_json_str,
                # Per-instrument sub-dicts serialised inside loop (correct)
                "bid_ask_quote_json": _jsonify(market_level.get("bidAskQuote", [])),
                "market_ohlc_json":   _jsonify(market_ohlc.get("ohlc", [])),
                "ltpc_json":          _jsonify(ltpc),
                "e_feed_json":        _jsonify(e_feed),
                "market_level_json":  _jsonify(market_level),
                "feed_data_json":     _jsonify(feed_data),
                "full_feed_json":     _jsonify(full_feed),
            }
            self._append("raw", row)

    def record_tick(self, tick: Any) -> None:
        """Persist one parsed tick as a normalised Parquet row."""
        if not self.enabled:
            return
        if is_dataclass(tick):
            row = asdict(tick)
        elif isinstance(tick, Mapping):
            row = dict(tick)
        else:
            raise TypeError(f"Unsupported tick type: {type(tick).__name__}")

        row        = {key: _normalize_scalar(value) for key, value in row.items()}
        event_time = row.get("ltt") or row.get("received_at") or datetime.now()
        if not isinstance(event_time, datetime):
            event_time = pd.Timestamp(event_time).to_pydatetime()
        row["event_time"] = event_time
        row["symbol"]     = row.get("symbol", "UNKNOWN")
        self._append("ticks", row)

    def record_candle(self, symbol: str, candle: Mapping[str, Any]) -> None:
        """Persist one completed candle row."""
        if not self.enabled:
            return
        row        = {key: _normalize_scalar(value) for key, value in dict(candle).items()}
        event_time = row.get("datetime") or datetime.now()
        if not isinstance(event_time, datetime):
            event_time = pd.Timestamp(event_time).to_pydatetime()
        row["event_time"] = event_time
        row["symbol"]     = symbol
        self._append("candles", row)

    def close(self) -> None:
        self.flush()


live_data_storage = LiveMarketDataStorage()


__all__ = ["LiveMarketDataStorage", "live_data_storage"]