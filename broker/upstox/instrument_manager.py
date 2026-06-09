"""
broker/upstox/instrument_manager.py
------------------------------------
Instrument key lookup for all Upstox-traded securities.

SUPPORTED INSTRUMENT TYPES
===========================
    EQUITY  - Equities        (NSE_EQ, BSE_EQ)
    INDEX   - Indices         (NSE_INDEX, BSE_INDEX)
    FUTSTK  - Stock Futures   (NSE_FO, BSE_FO)
    FUTIDX  - Index Futures   (NSE_FO, BSE_FO)
    FUTCOM  - Commodity Fut.  (MCX_FO, NSE_COM)
    FUTCUR  - Currency Fut.   (NCD_FO, BCD_FO)
    FUTIRT  - IR Futures      (BCD_FO)
    OPTSTK  - Stock Options   (NSE_FO, BSE_FO)
    OPTIDX  - Index Options   (NSE_FO, BSE_FO)
    OPTCOM  - Commodity Opts  (NSE_COM, MCX_FO)
    OPTCUR  - Currency Opts   (NCD_FO, BCD_FO)
    OPTIRD  - IR Options      (BCD_FO)

USAGE
=====
::

    from broker.upstox.instrument_manager import get_instrument_key

    key = get_instrument_key("EQUITY", "NSE", "INFY")
    key = get_instrument_key("FUTSTK", "NSE", "RELIANCE", expiry="30MAR26")
    key = get_instrument_key(
        "OPTIDX", "NSE", "NIFTY",
        option_type="CE", expiry="30MAR26", strike=25500
    )

P1 FIX (2026-04-11) — O(n) linear scan replaced with O(1) dict lookup
=======================================================================
Previously ``get_instrument_key()`` called ``download_and_save_instrument_list()``
on every invocation and then iterated the full ~100 000-entry JSON list
sequentially. One equity lookup took ~50 ms; an options chain scan could
exceed 500 ms. With the screener calling this per symbol and the data manager
calling it per download chunk, the cost compounded to minutes.

Fix: a module-level ``_INSTRUMENT_CACHE`` dict is built once per process
(lazily, on first call after a file-stale check). The cache maps
``(segment, trading_symbol.upper()) → list[instrument_dict]`` so all
subsequent calls skip the linear scan entirely.

Cache invalidation:
  - ``force_download=True`` in ``download_and_save_instrument_list()`` also
    clears the in-memory cache so a re-download triggers a cache rebuild.
  - The cache is invalidated automatically if the instrument file is
    re-downloaded (stale > 7 AM IST), because the next lookup rebuilds from
    the new data.

The lookup logic inside ``get_instrument_key`` is identical to the original
except the full-list iteration is replaced with targeted dict lookups.
"""

import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # pragma: no cover - dependency is optional in tests
    requests = None

from config import config

logger = logging.getLogger(__name__)


def _require_requests() -> None:
    """Raise a clear error when the requests dependency is absent."""
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required for instrument list downloads."
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

complete_instru_list = config.INSTRUMENT_KEY_URL

DATA_DIR = config.DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

INSTRUMENT_DATA_FILE = config.INSTRUMENT_KEY_PATH
INSTRUMENT_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# P1 FIX: In-process cache
# ---------------------------------------------------------------------------

# Module-level cache — built once per process, invalidated on force_download.
# Maps (segment, trading_symbol_upper) -> [instrument_dict, ...]
_INSTRUMENT_CACHE: Optional[Dict[tuple, List[dict]]] = None
# The raw list (still needed for the expiry-range matching on futures/options)
_INSTRUMENT_LIST: Optional[List[dict]] = None


def _build_cache(instrument_data: List[dict]) -> Dict[tuple, List[dict]]:
    """
    Build the O(1) lookup dict from the raw instrument list.

    Key: (segment, trading_symbol.upper())
    Value: list of matching instrument dicts.

    Building is O(n) but happens only once per process/file-reload.
    All subsequent lookups are O(1).
    """
    cache: Dict[tuple, List[dict]] = {}
    for instr in instrument_data:
        seg = instr.get("segment", "")
        sym = instr.get("trading_symbol", "").upper()
        key = (seg, sym)
        if key not in cache:
            cache[key] = []
        cache[key].append(instr)
        # Also index by asset_symbol for futures and options
        asset_sym = instr.get("asset_symbol", "").upper()
        if asset_sym and asset_sym != sym:
            asset_key = (seg, asset_sym)
            if asset_key not in cache:
                cache[asset_key] = []
            cache[asset_key].append(instr)
    logger.debug("Instrument cache built: %d segment/symbol pairs", len(cache))
    return cache


def _invalidate_cache() -> None:
    """Clear both the in-memory cache and raw list."""
    global _INSTRUMENT_CACHE, _INSTRUMENT_LIST
    _INSTRUMENT_CACHE = None
    _INSTRUMENT_LIST  = None


# ---------------------------------------------------------------------------
# Download / cache
# ---------------------------------------------------------------------------

def download_and_save_instrument_list(force_download: bool = False) -> List[dict]:
    """
    Download instrument list from Upstox URL and save locally.
    Check local cache first before downloading.
    Re-download if the file was last modified before today's 7 AM IST.

    P1 FIX: Clears ``_INSTRUMENT_CACHE`` and ``_INSTRUMENT_LIST`` whenever
    a new download is performed so the next ``get_instrument_key()`` call
    rebuilds from the fresh data.

    Args:
        force_download: If True, always download and rebuild.

    Returns:
        list: Parsed instrument data (list of dicts).
    """
    global _INSTRUMENT_CACHE, _INSTRUMENT_LIST

    if requests is None and not INSTRUMENT_DATA_FILE.exists():
        raise RuntimeError(
            "The 'requests' package is required to download the Upstox "
            "instrument list, and no local cache is available."
        )

    # Check if local file exists and is recent enough
    if INSTRUMENT_DATA_FILE.exists() and not force_download:
        ist_tz     = ZoneInfo("Asia/Kolkata")
        file_mtime = datetime.fromtimestamp(
            INSTRUMENT_DATA_FILE.stat().st_mtime, tz=ist_tz
        )
        today_7am  = datetime.now(tz=ist_tz).replace(
            hour=7, minute=0, second=0, microsecond=0
        )

        if file_mtime >= today_7am:
            # File is fresh — use it (and in-memory cache if already built)
            if _INSTRUMENT_LIST is not None:
                logger.debug("Returning in-process instrument list (already loaded).")
                return _INSTRUMENT_LIST
            logger.info(
                "Loading instrument data from local cache: %s", INSTRUMENT_DATA_FILE
            )
            with open(INSTRUMENT_DATA_FILE, "r") as f:
                data = json.load(f)
            _INSTRUMENT_LIST = data
            return data
        else:
            logger.info(
                "Instrument file is from %s (before today's 7 AM IST). Re-downloading.",
                file_mtime.strftime("%Y-%m-%d %H:%M IST"),
            )

    logger.info("Downloading instrument list from: %s", complete_instru_list)
    try:
        _require_requests()
        response = requests.get(complete_instru_list, timeout=30)
        response.raise_for_status()

        decompressed_data = gzip.decompress(response.content)
        instrument_data   = json.loads(decompressed_data.decode("utf-8"))

        with open(INSTRUMENT_DATA_FILE, "w") as f:
            json.dump(instrument_data, f, indent=2)

        logger.info(
            "Instrument list downloaded and saved to: %s (%s instruments)",
            INSTRUMENT_DATA_FILE, f"{len(instrument_data):,}",
        )

        # P1 FIX: invalidate in-memory caches so they rebuild from new data
        _invalidate_cache()
        _INSTRUMENT_LIST = instrument_data
        return instrument_data

    except Exception as e:
        logger.error("Error downloading instrument list: %s", e)
        if INSTRUMENT_DATA_FILE.exists():
            logger.warning("Download failed. Using local cache as fallback.")
            with open(INSTRUMENT_DATA_FILE, "r") as f:
                data = json.load(f)
            _INSTRUMENT_LIST = data
            return data
        raise


# ---------------------------------------------------------------------------
# P1 FIX: Cache accessor (lazy build)
# ---------------------------------------------------------------------------

def _get_cache() -> Dict[tuple, List[dict]]:
    """
    Return the in-process instrument lookup cache, building it if needed.

    Thread safety note: in CPython the GIL means that simultaneous
    calls on the first invocation may both trigger a build, but the
    result is idempotent (same data → same cache), so the only cost is
    a redundant build, not a race condition.
    """
    global _INSTRUMENT_CACHE
    if _INSTRUMENT_CACHE is None:
        data = download_and_save_instrument_list()
        _INSTRUMENT_CACHE = _build_cache(data)
    return _INSTRUMENT_CACHE


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def get_instrument_key(
    instrument_type: str,
    exchange:        str,
    trading_symbol:  str,
    option_type:     Optional[str] = None,
    expiry:          Optional[str] = None,
    strike:          Optional[float] = None,
) -> str:
    """
    Get the Upstox instrument_key for any tradeable security.

    P1 FIX: Replaced the O(n) full-list scan with an O(1) dict lookup for
    the candidate-filtering step. The expiry/strike matching for futures and
    options still iterates over the (small) candidate list for that
    symbol+segment combination — typically 1–12 entries.

    Args:
        instrument_type: Type of instrument (case-insensitive).
                         e.g. "EQUITY", "FUTSTK", "OPTIDX"
        exchange:        Exchange - NSE, BSE, MCX (case-insensitive).
        trading_symbol:  Symbol or underlying (case-insensitive).
                         e.g. "INFY", "NIFTY", "RELIANCE"
        option_type:     For options only - "CE" or "PE".
        expiry:          For F&O - date in DDMONYY format e.g. "27MAR26".
        strike:          For options only - strike price.

    Returns:
        str: Upstox instrument_key e.g. "NSE_EQ|INE009A01021".

    Raises:
        ValueError: If required parameters are missing or instrument not found.
    """
    # ── Segment search strategy mapping ──────────────────────────────────────
    segment_search_strategy = {
        "EQUITY": [
            {"segments": ["NSE_EQ", "BSE_EQ"], "data_instr_type": None, "asset_type": None}
        ],
        "INDEX": [
            {"segments": ["NSE_INDEX", "BSE_INDEX"], "data_instr_type": "INDEX", "asset_type": None}
        ],
        "FUTSTK": [
            {"segments": ["NSE_FO", "BSE_FO"], "data_instr_type": "FUT", "asset_type": "EQUITY"}
        ],
        "FUTIDX": [
            {"segments": ["NSE_FO", "BSE_FO"], "data_instr_type": "FUT", "asset_type": "INDEX"}
        ],
        "FUTCOM": [
            {"segments": ["MCX_FO", "NSE_COM"], "data_instr_type": "FUT", "asset_type": "COM"}
        ],
        "FUTCUR": [
            {"segments": ["NCD_FO", "BCD_FO"], "data_instr_type": "FUT", "asset_type": "CUR"}
        ],
        "FUTIRT": [
            {"segments": ["BCD_FO"], "data_instr_type": "FUT", "asset_type": "IRD"}
        ],
        "OPTSTK": [
            {"segments": ["NSE_FO", "BSE_FO"], "data_instr_type": ["CE", "PE"], "asset_type": "EQUITY"}
        ],
        "OPTIDX": [
            {"segments": ["NSE_FO", "BSE_FO"], "data_instr_type": ["CE", "PE"], "asset_type": "INDEX"}
        ],
        "OPTCOM": [
            {"segments": ["NSE_COM", "MCX_FO"], "data_instr_type": ["CE", "PE"], "asset_type": "COM"}
        ],
        "OPTCUR": [
            {"segments": ["NCD_FO", "BCD_FO"], "data_instr_type": ["CE", "PE"], "asset_type": "CUR"}
        ],
        "OPTIRD": [
            {"segments": ["BCD_FO"], "data_instr_type": ["CE", "PE"], "asset_type": "IRD"}
        ],
    }

    # ── Segment → exchange mapping ────────────────────────────────────────────
    segment_exchange_map = {
        "NSE_EQ":    "NSE", "BSE_EQ":    "BSE",
        "NSE_INDEX": "NSE", "BSE_INDEX": "BSE",
        "NSE_FO":    "NSE", "BSE_FO":    "BSE",
        "MCX_FO":    "MCX",
        "NSE_COM":   "NSE",
        "NCD_FO":    "NSE",   # Special case: segment=NCD_FO but exchange=NSE
        "BCD_FO":    "BSE",   # Special case: segment=BCD_FO but exchange=BSE
    }

    # ── Normalise inputs ──────────────────────────────────────────────────────
    instrument_type = instrument_type.upper().strip()
    exchange        = exchange.upper().strip()
    trading_symbol  = trading_symbol.upper().strip()
    if option_type:  option_type = option_type.upper().strip()
    if expiry:       expiry      = expiry.upper().strip()
    if strike is not None: strike = float(strike)

    # ── Validate instrument type ──────────────────────────────────────────────
    if instrument_type not in segment_search_strategy:
        raise ValueError(
            f"Unknown instrument type: {instrument_type}. "
            f"Supported types: {', '.join(segment_search_strategy.keys())}"
        )

    # ── Validate required parameters ─────────────────────────────────────────
    if instrument_type in ("OPTSTK", "OPTIDX", "OPTCUR", "OPTCOM", "OPTIRT"):
        if not option_type or not expiry or strike is None:
            raise ValueError(
                f"For {instrument_type}, option_type, expiry, and strike are required. "
                f"Received: option_type={option_type}, expiry={expiry}, strike={strike}"
            )

    if instrument_type in ("FUTSTK", "FUTIDX", "FUTCOM", "FUTCUR", "FUTIRT"):
        if not expiry:
            raise ValueError(f"Expiry is required for {instrument_type}")

    # ── Helper: expiry string → ms timestamp range ────────────────────────────
    def get_expiry_range(expiry_str: str):
        try:
            dt = datetime.strptime(expiry_str, "%d%b%y")
            ts = int(dt.timestamp() * 1000)
            return ts - 3_600_000, ts + 86_400_000
        except ValueError:
            return None, None

    # ── P1 FIX: use the cached dict instead of iterating the full list ────────
    cache = _get_cache()

    search_strategies = segment_search_strategy[instrument_type]

    for strategy in search_strategies:
        segments_to_search = strategy["segments"]
        data_instr_types   = strategy["data_instr_type"]
        asset_type_filter  = strategy["asset_type"]

        # Normalise data_instr_types for consistent handling
        if data_instr_types is None:
            data_instr_types = [None]
        elif isinstance(data_instr_types, str):
            data_instr_types = [data_instr_types]
        elif not isinstance(data_instr_types, list):
            data_instr_types = [data_instr_types]

        for seg in segments_to_search:
            # Verify the segment's exchange matches the requested exchange
            if segment_exchange_map.get(seg) != exchange:
                continue

            # O(1) candidate fetch from cache
            candidates = cache.get((seg, trading_symbol), [])
            if not candidates:
                continue

            for instrument in candidates:
                # Filter by instrument_type field (EQ, FUT, CE, PE, INDEX)
                instr_type = instrument.get("instrument_type", "").upper()
                if data_instr_types != [None]:
                    if instr_type not in data_instr_types:
                        continue

                # Filter by asset_type (EQUITY, INDEX, COM, CUR, IRD)
                if asset_type_filter:
                    if instrument.get("asset_type") != asset_type_filter:
                        continue

                # ── EQUITY / INDEX — direct match ─────────────────────────────
                if instrument_type in ("EQUITY", "INDEX"):
                    key = instrument.get("instrument_key", "")
                    logger.info("Found %s: %s -> %s", instrument_type, trading_symbol, key)
                    return key

                # ── FUTURES — expiry match ────────────────────────────────────
                elif instrument_type in ("FUTSTK", "FUTIDX", "FUTCOM", "FUTCUR", "FUTIRT"):
                    exp_min, exp_max = get_expiry_range(expiry)
                    if exp_min is None:
                        raise ValueError(
                            f"Invalid expiry format: {expiry}. "
                            "Use format: DDMONYY (e.g., 24FEB26)"
                        )
                    instr_expiry = instrument.get("expiry", 0)
                    if isinstance(instr_expiry, (int, float)):
                        if exp_min <= instr_expiry <= exp_max:
                            key = instrument.get("instrument_key", "")
                            logger.info(
                                "Found %s: %s expiry=%s -> %s",
                                instrument_type, trading_symbol, expiry, key,
                            )
                            return key

                # ── OPTIONS — option_type + strike + expiry match ─────────────
                elif instrument_type in ("OPTSTK", "OPTIDX", "OPTCOM", "OPTCUR", "OPTIRD"):
                    instr_option_type = instrument.get("instrument_type", "").upper()
                    if instr_option_type != option_type:
                        continue
                    strike_price = instrument.get("strike_price", 0)
                    if abs(float(strike_price) - float(strike)) > 0.01:
                        continue
                    exp_min, exp_max = get_expiry_range(expiry)
                    if exp_min is None:
                        raise ValueError(
                            f"Invalid expiry format: {expiry}. "
                            "Use format: DDMONYY (e.g., 24FEB26)"
                        )
                    instr_expiry = instrument.get("expiry", 0)
                    if isinstance(instr_expiry, (int, float)):
                        if exp_min <= instr_expiry <= exp_max:
                            key = instrument.get("instrument_key", "")
                            logger.info(
                                "Found %s: %s %s strike=%s expiry=%s -> %s",
                                instrument_type, trading_symbol,
                                option_type, strike, expiry, key,
                            )
                            return key

    # ── Nothing found ─────────────────────────────────────────────────────────
    searched_segments = [
        seg
        for strat in search_strategies
        for seg in strat["segments"]
    ]
    raise ValueError(
        f"No {instrument_type} found for {trading_symbol} on {exchange}. "
        f"Searched segments: {searched_segments}. "
        f"Additional filters: expiry={expiry}, strike={strike}, option_type={option_type}"
    )