"""
data/universe.py
================
Stock-universe management and cross-provider symbol normalisation.

Provides pre-built index universes (Nifty 50/100/200/500) with
local JSON caching, custom watchlist support, and a ``SymbolMapper``
for translating symbols between providers (yfinance, Upstox, display).

Usage
-----
    from data.universe import UniverseManager, SymbolMapper

    um = UniverseManager()
    nifty50 = um.get_universe("NIFTY_50")

    sm = SymbolMapper()
    yf_sym = sm.to_yfinance("RELIANCE")  # → "RELIANCE.NS"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import config

logger = logging.getLogger(__name__)

__all__ = [
    "UniverseManager",
    "SymbolMapper",
    "NIFTY_50",
    "NIFTY_100",
    "NIFTY_200",
    "NIFTY_500",
    "ALL_NSE",
]

# ── Universe name constants ──────────────────────────────────────────────────

NIFTY_50: str = "NIFTY_50"
NIFTY_100: str = "NIFTY_100"
NIFTY_200: str = "NIFTY_200"
NIFTY_500: str = "NIFTY_500"
ALL_NSE: str = "ALL_NSE"

# ── Directory for cached universe JSON files ─────────────────────────────────

UNIVERSE_DIR: Path = config.UNIVERSE_DIR

# ── Hardcoded fallback: Nifty 50 constituents (as of Jun 2025) ───────────────
# Used only when the JSON file has not been downloaded yet.

_NIFTY_50_FALLBACK: list[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL",
    "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
    "ITC", "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "NTPC", "NESTLEIND",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]


class UniverseManager:
    """Manage stock universes and custom watchlists.

    Universes are stored as JSON files in ``data/universes/``.
    If a universe file does not exist, hardcoded fallbacks are used
    for Nifty 50; other universes return empty with a warning.
    """

    def __init__(self, universe_dir: Path | None = None) -> None:
        self._dir: Path = universe_dir or UNIVERSE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Core API ──────────────────────────────────────────────────────

    def get_universe(self, name: str) -> list[str]:
        """Return the symbol list for a named universe.

        Parameters
        ----------
        name : str
            Universe name (e.g. ``"NIFTY_50"``).

        Returns
        -------
        list[str]
            Sorted list of trading symbols.
        """
        name = name.strip().upper()

        # Try loading from JSON cache
        symbols = self._load_from_file(name)
        if symbols:
            return symbols

        # Hardcoded fallback for NIFTY_50
        if name == NIFTY_50:
            logger.info(
                "Using hardcoded Nifty 50 fallback — run "
                "'python -m data.universe_updater' to fetch latest"
            )
            return sorted(_NIFTY_50_FALLBACK)

        logger.warning(
            "Universe %r not found. Run 'python -m data.universe_updater' "
            "to download index constituents.",
            name,
        )
        return []

    def list_universes(self) -> list[str]:
        """List all available universe names (from cached files + built-in)."""
        names: set[str] = {NIFTY_50}  # always available via fallback
        for f in self._dir.glob("*.json"):
            names.add(f.stem.upper())
        # Include custom watchlists
        for f in self._dir.glob("custom_*.json"):
            names.add(f.stem.upper())
        return sorted(names)

    def add_custom_watchlist(self, name: str, symbols: list[str]) -> None:
        """Save a custom watchlist.

        Parameters
        ----------
        name : str
            Watchlist name (stored as ``custom_<name>.json``).
        symbols : list[str]
            Trading symbols.
        """
        name = name.strip().upper()
        clean = sorted({s.strip().upper() for s in symbols if s.strip()})
        file_path = self._dir / f"custom_{name}.json"
        self._save_to_file(file_path, clean)
        logger.info("Saved custom watchlist %r with %d symbols", name, len(clean))

    def load_watchlist_from_file(self, file_path: Path) -> list[str]:
        """Load a watchlist from a CSV or JSON file.

        For CSV: expects a column named ``symbol`` or the first column.
        For JSON: expects a JSON array of strings.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Watchlist file not found: {file_path}")

        suffix = file_path.suffix.lower()

        if suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return sorted({str(s).strip().upper() for s in data if s})
            if isinstance(data, dict) and "symbols" in data:
                return sorted({str(s).strip().upper() for s in data["symbols"] if s})
            raise ValueError(f"Unexpected JSON structure in {file_path}")

        if suffix == ".csv":
            import csv

            symbols: list[str] = []
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Try 'symbol', 'Symbol', 'SYMBOL', or first column
                field_name = None
                if reader.fieldnames:
                    for candidate in ("symbol", "Symbol", "SYMBOL"):
                        if candidate in reader.fieldnames:
                            field_name = candidate
                            break
                    if field_name is None:
                        field_name = reader.fieldnames[0]

                for row in reader:
                    val = row.get(field_name, "").strip().upper()
                    if val:
                        symbols.append(val)
            return sorted(set(symbols))

        raise ValueError(f"Unsupported file type: {suffix}. Use .json or .csv")

    def get_symbol_info(self, symbol: str) -> dict[str, Any] | None:
        """Return basic info for a symbol (if available).

        Currently returns membership info — which universes contain
        the symbol.  Future: sector, industry, market cap, etc.
        """
        symbol = symbol.strip().upper()
        memberships: list[str] = []
        for name in self.list_universes():
            if symbol in self.get_universe(name):
                memberships.append(name)
        if not memberships:
            return None
        return {"symbol": symbol, "universes": memberships}

    # ── Persistence helpers ───────────────────────────────────────────

    def _load_from_file(self, name: str) -> list[str]:
        """Load symbols from the JSON cache file."""
        file_path = self._dir / f"{name}.json"
        if not file_path.exists():
            # Try custom_ prefix
            file_path = self._dir / f"custom_{name}.json"
            if not file_path.exists():
                return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return sorted(data)
            if isinstance(data, dict) and "symbols" in data:
                return sorted(data["symbols"])
            return []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load %s: %s", file_path, exc)
            return []

    @staticmethod
    def _save_to_file(file_path: Path, symbols: list[str]) -> None:
        """Write symbols to a JSON file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(symbols, f, indent=2, ensure_ascii=False)

    def save_universe(self, name: str, symbols: list[str]) -> None:
        """Persist a universe to the JSON cache.

        Called by ``universe_updater.py`` after fetching fresh data.
        """
        name = name.strip().upper()
        clean = sorted({s.strip().upper() for s in symbols if s.strip()})
        file_path = self._dir / f"{name}.json"
        self._save_to_file(file_path, clean)
        logger.info("Saved universe %r with %d symbols", name, len(clean))


class SymbolMapper:
    """Cross-provider symbol normalisation.

    Translates between canonical trading symbols (e.g. ``RELIANCE``)
    and provider-specific formats (e.g. ``RELIANCE.NS`` for yfinance).
    """

    # NSE suffix for yfinance
    _YF_SUFFIX: dict[str, str] = {
        "NSE": ".NS",
        "BSE": ".BO",
    }

    @staticmethod
    def normalize(symbol: str) -> str:
        """Strip whitespace and uppercase."""
        return symbol.strip().upper()

    def to_yfinance(self, symbol: str, exchange: str = "NSE") -> str:
        """Convert to yfinance ticker format.

        Examples
        --------
        >>> SymbolMapper().to_yfinance("RELIANCE")
        'RELIANCE.NS'
        >>> SymbolMapper().to_yfinance("RELIANCE", exchange="BSE")
        'RELIANCE.BO'
        """
        sym = self.normalize(symbol)
        suffix = self._YF_SUFFIX.get(exchange.upper(), ".NS")

        # Handle M&M → M%26M (yfinance URL-encodes &)
        # Actually yfinance accepts M&M.NS directly, but some
        # special symbols need care
        return f"{sym}{suffix}"

    def to_upstox(self, symbol: str, exchange: str = "NSE") -> str:
        """Return the canonical Upstox trading symbol.

        For now, Upstox uses the same symbol as NSE/BSE.
        The instrument_key is resolved separately by instrument_manager.
        """
        return self.normalize(symbol)

    def to_display(self, symbol: str) -> str:
        """Return a human-readable display name.

        Strips provider suffixes (.NS, .BO) if present.
        """
        sym = symbol.strip().upper()
        for suffix in (".NS", ".BO"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
        return sym

    def from_yfinance(self, yf_symbol: str) -> str:
        """Convert a yfinance ticker back to canonical symbol."""
        return self.to_display(yf_symbol)
