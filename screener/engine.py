"""
screener/engine.py
------------------
Standalone screener module that reuses the indicator and strategy stack.

Use cases:
  - Run a multi-ticker screen using existing strategies and indicators.
  - Keep the screener output compatible with dashboards or CLI summaries.
  - Reuse the ``algodesk.data_plan`` loader so instrument-aware defaults apply.

P0 FIX (2026-04-11) — filter_hours TypeError crashes all tickers silently
==========================================================================
``_default_loader`` was passing ``filter_hours=config.filter_hours`` to
``UpstoxDataAdapter.fetch_ohlcv()``. That method has no ``filter_hours``
parameter, so every call raised:

    TypeError: fetch_ohlcv() got an unexpected keyword argument 'filter_hours'

Because ``ScreenerEngine.run()`` wraps each ticker fetch in a bare
``except Exception``, the TypeError was silently swallowed for every
ticker — the screener completed with zero results and no visible error.

Fix: remove ``filter_hours`` from the ``fetch_ohlcv`` call.
``ScreenerConfig.filter_hours`` is kept for future use when the data
adapter gains support for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd

from broker.upstox.data_adapter import UpstoxDataAdapter
from screener.base import ScreenResult, ScreenerConfig, ScreenRule

logger = logging.getLogger(__name__)


Loader = Callable[[ScreenerConfig, str], pd.DataFrame]


@dataclass(slots=True)
class ScreenerEngine:
    config: ScreenerConfig
    rules: Sequence[ScreenRule]
    loader: Loader = field(default_factory=lambda: _default_loader)

    def run(self) -> List[ScreenResult]:
        if not self.rules:
            raise ValueError("At least one screening rule must be provided.")
        results: List[ScreenResult] = []
        for ticker in self.config.tickers:
            try:
                df = self.loader(self.config, ticker)
            except Exception as exc:
                logger.warning("Skipping %s: %s", ticker, exc)
                continue
            for rule in self.rules:
                meta = rule.evaluate(df)
                result = ScreenResult(
                    ticker=ticker,
                    passed=meta is not None,
                    rule_name=rule.name,
                    timestamp=meta.get("timestamp") if meta else None,
                    details=meta or {},
                )
                results.append(result)
        return results


def _default_loader(config: ScreenerConfig, ticker: str) -> pd.DataFrame:
    """
    Fetch OHLCV data for a single ticker using the Upstox data adapter.

    P0 FIX: ``filter_hours`` has been removed from this call.
    ``UpstoxDataAdapter.fetch_ohlcv`` does not accept that parameter;
    passing it caused a TypeError that silently dropped every ticker.
    ``ScreenerConfig.filter_hours`` is preserved for future use.
    """
    return UpstoxDataAdapter().fetch_ohlcv(
        instrument_type=config.instrument_type,
        exchange=config.exchange,
        trading_symbol=ticker,
        unit=config.unit,
        interval=config.interval,
        from_date=config.from_date,
        to_date=config.to_date,
        period=config.period,
        #filter_hours=config.filter_hours, 
        # filter_hours is intentionally omitted — UpstoxDataAdapter.fetch_ohlcv
        # does not support this parameter as of the current adapter version.
        # When adapter support is added, wire it back here.
    )