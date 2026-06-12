"""
data/universe_updater.py
========================
Standalone script to refresh index constituent lists from NSE India.

Downloads the current Nifty 50/100/200/500 constituent CSVs, compares
against the locally cached versions, logs additions/removals, and
saves updated JSON files to ``data/universes/``.

Usage
-----
    # Command line
    python -m data.universe_updater

    # Programmatic
    from data.universe_updater import UniverseUpdater
    updater = UniverseUpdater()
    results = updater.update_all()
"""

from __future__ import annotations

import io
import csv
import logging
from pathlib import Path
from typing import Any

import requests

from config import config
from data.universe import UniverseManager, NIFTY_50, NIFTY_100, NIFTY_200, NIFTY_500

logger = logging.getLogger(__name__)

__all__ = ["UniverseUpdater"]

# ── NSE index constituent CSV URLs ───────────────────────────────────────────
# These URLs serve CSVs with columns including "Symbol" (trading symbol).
# Headers are required to avoid 403 from NSE's CDN.

_INDEX_URLS: dict[str, str] = {
    NIFTY_50: (
        "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
    ),
    NIFTY_100: (
        "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
    ),
    NIFTY_200: (
        "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    ),
    NIFTY_500: (
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    ),
}

# Browser-like headers to avoid 403/blocking from NSE
_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_REQUEST_TIMEOUT: int = 30  # seconds


class UniverseUpdater:
    """Fetch and update index constituent lists from NSE India.

    Parameters
    ----------
    universe_mgr : UniverseManager | None
        If not provided, creates a default instance.
    """

    def __init__(
        self,
        universe_mgr: UniverseManager | None = None,
    ) -> None:
        self._mgr: UniverseManager = universe_mgr or UniverseManager()

    def update_all(self) -> dict[str, dict[str, Any]]:
        """Update all known index universes.

        Returns
        -------
        dict
            Keyed by universe name.  Each value contains:
            ``count``, ``added``, ``removed``, ``success``.
        """
        results: dict[str, dict[str, Any]] = {}
        for name in _INDEX_URLS:
            results[name] = self.update_universe(name)
        return results

    def update_universe(self, name: str) -> dict[str, Any]:
        """Fetch and save a single universe.

        Parameters
        ----------
        name : str
            Universe name (e.g. ``"NIFTY_50"``).

        Returns
        -------
        dict
            ``count``, ``added``, ``removed``, ``success``, ``error``.
        """
        name = name.strip().upper()
        url = _INDEX_URLS.get(name)
        if not url:
            logger.error("No URL configured for universe %r", name)
            return {
                "count": 0,
                "added": [],
                "removed": [],
                "success": False,
                "error": f"No URL for {name}",
            }

        logger.info("Fetching %s from %s", name, url)

        try:
            new_symbols = self._fetch_symbols_from_url(url)
        except Exception as exc:
            logger.error("Failed to fetch %s: %s", name, exc)
            return {
                "count": 0,
                "added": [],
                "removed": [],
                "success": False,
                "error": str(exc),
            }

        if not new_symbols:
            logger.warning("No symbols parsed from %s — skipping update", name)
            return {
                "count": 0,
                "added": [],
                "removed": [],
                "success": False,
                "error": "No symbols found in response",
            }

        # Compare with existing
        old_symbols = set(self._mgr.get_universe(name))
        new_set = set(new_symbols)

        added = sorted(new_set - old_symbols)
        removed = sorted(old_symbols - new_set)

        if added:
            logger.info("%s additions: %s", name, ", ".join(added))
        if removed:
            logger.info("%s removals: %s", name, ", ".join(removed))

        # Save
        self._mgr.save_universe(name, list(new_set))
        logger.info(
            "%s updated: %d symbols (%d added, %d removed)",
            name,
            len(new_set),
            len(added),
            len(removed),
        )

        return {
            "count": len(new_set),
            "added": added,
            "removed": removed,
            "success": True,
            "error": "",
        }

    @staticmethod
    def _fetch_symbols_from_url(url: str) -> list[str]:
        """Download a CSV from NSE and extract trading symbols.

        The CSV is expected to have a column named ``Symbol`` (case-
        insensitive match).  Falls back to the first column if
        ``Symbol`` is not found.
        """
        response = requests.get(
            url,
            headers=_REQUEST_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        content = response.text
        reader = csv.DictReader(io.StringIO(content))

        # Find the symbol column (case-insensitive)
        field_name: str | None = None
        if reader.fieldnames:
            for candidate in reader.fieldnames:
                if candidate.strip().lower() == "symbol":
                    field_name = candidate
                    break
            if field_name is None and reader.fieldnames:
                field_name = reader.fieldnames[0]

        if field_name is None:
            raise ValueError("Could not identify symbol column in CSV")

        symbols: list[str] = []
        for row in reader:
            val = row.get(field_name, "").strip().upper()
            if val:
                symbols.append(val)

        return sorted(set(symbols))


# ── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point: update all universes and print summary."""
    from config import setup_logging

    setup_logging()
    logger.info("=" * 50)
    logger.info("AlgoDesk Universe Updater")
    logger.info("=" * 50)

    updater = UniverseUpdater()
    results = updater.update_all()

    print("\n" + "=" * 55)
    print("  UNIVERSE UPDATE SUMMARY")
    print("=" * 55)

    for name, info in results.items():
        status = "✅" if info["success"] else "❌"
        print(f"  {status} {name:12s} : {info['count']:4d} symbols", end="")
        if info["added"]:
            print(f"  (+{len(info['added'])} added)", end="")
        if info["removed"]:
            print(f"  (-{len(info['removed'])} removed)", end="")
        if info["error"]:
            print(f"  ERROR: {info['error']}", end="")
        print()

    print("=" * 55)


if __name__ == "__main__":
    main()
