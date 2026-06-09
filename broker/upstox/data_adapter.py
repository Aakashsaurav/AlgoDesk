"""
broker/upstox/data_adapter.py
=============================
Thin adapter around the Upstox historical data manager.

This file keeps the phase-1 data layer discoverable from the broker package
while delegating the actual work to ``broker.upstox.data_manager``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

from broker.upstox.instrument_manager import get_instrument_key


@dataclass(slots=True)
class UpstoxDataAdapter:
    """
    Backward-friendly adapter for OHLCV and instrument-key lookup.
    """

    def fetch_ohlcv(
        self,
        instrument_type: str,
        exchange: str,
        trading_symbol: str,
        unit: str,
        interval: int,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        period: Optional[str] = None,
        option_type: Optional[str] = None,
        expiry: Optional[str] = None,
        strike: Optional[float] = None,
    ) -> Any:
        from broker.upstox.data_manager import get_ohlcv

        return get_ohlcv(
            instrument_type=instrument_type,
            exchange=exchange,
            trading_symbol=trading_symbol,
            unit=unit,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            period=period,
            option_type=option_type,
            expiry=expiry,
            strike=strike,
        )

    def resolve_instrument_key(
        self,
        instrument_type: str,
        exchange: str,
        trading_symbol: str,
        option_type: Optional[str] = None,
        expiry: Optional[str] = None,
        strike: Optional[float] = None,
    ) -> str:
        return get_instrument_key(
            instrument_type=instrument_type,
            exchange=exchange,
            trading_symbol=trading_symbol,
            option_type=option_type,
            expiry=expiry,
            strike=strike,
        )


__all__ = ["UpstoxDataAdapter"]
