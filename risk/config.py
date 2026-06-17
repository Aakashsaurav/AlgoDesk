# Use cases:
# - Encapsulate tunable risk limits (daily loss, max positions).
# - Share the same structure between the risk guard and configuration sources.
"""
risk/config.py
--------------
Configuration helpers for the standalone risk engine.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass(slots=True)
class RiskConfig:
    """
    Risk limits enforced by the risk engine.
    Note: All percentage fields use actual percentages (e.g. 2.0 = 2%), not fractions.
    """

    # Capital
    initial_capital: float = 500_000.0

    # Loss limits
    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 10.0

    # Position limits
    max_positions: int = 5
    max_position_size_pct: float = 20.0
    pyramid_max: int = 1

    # Directional
    allow_shorting: bool = False

    # Intraday
    intraday_squareoff: bool = True
    squareoff_time_str: str = "15:20"

    # Live-specific
    kill_switch: bool = False
    daily_loss_reset_time_str: str = "09:00"

    # Lot size (F&O)
    lot_size: int = 1

    # Market hours (Indian market defaults)
    market_open_str: str = "09:15"
    market_close_str: str = "15:30"

    def __post_init__(self) -> None:
        """Basic validation upon instantiation."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid RiskConfig: {', '.join(errors)}")

    def validate(self) -> List[str]:
        """Validates configuration parameters and returns a list of error strings."""
        errors = []
        if self.initial_capital <= 0:
            errors.append("initial_capital must be > 0")
        if self.max_daily_loss_pct < 0:
            errors.append("max_daily_loss_pct must be >= 0")
        if self.max_drawdown_pct < 0:
            errors.append("max_drawdown_pct must be >= 0")
        if self.max_positions < 1:
            errors.append("max_positions must be >= 1")
        if not (0 < self.max_position_size_pct <= 100):
            errors.append("max_position_size_pct must be > 0 and <= 100")
        if self.pyramid_max < 1:
            errors.append("pyramid_max must be >= 1")
        if self.lot_size < 1:
            errors.append("lot_size must be >= 1")
        
        # Validate time strings
        for attr, name in [
            (self.squareoff_time_str, "squareoff_time_str"),
            (self.daily_loss_reset_time_str, "daily_loss_reset_time_str"),
            (self.market_open_str, "market_open_str"),
            (self.market_close_str, "market_close_str"),
        ]:
            try:
                datetime.datetime.strptime(attr, "%H:%M")
            except ValueError:
                errors.append(f"{name} must be in 'HH:MM' format")
                
        return errors

    def _parse_time(self, time_str: str) -> datetime.time:
        """Helper to parse 'HH:MM' into a time object."""
        return datetime.datetime.strptime(time_str, "%H:%M").time()

    @property
    def market_open_time(self) -> datetime.time:
        return self._parse_time(self.market_open_str)

    @property
    def market_close_time(self) -> datetime.time:
        return self._parse_time(self.market_close_str)

    @property
    def squareoff_time(self) -> datetime.time:
        return self._parse_time(self.squareoff_time_str)

    @property
    def daily_loss_reset_time(self) -> datetime.time:
        return self._parse_time(self.daily_loss_reset_time_str)

    def to_dict(self) -> Dict[str, Any]:
        """Returns the configuration as a dictionary."""
        return {
            "initial_capital": self.initial_capital,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_positions": self.max_positions,
            "max_position_size_pct": self.max_position_size_pct,
            "pyramid_max": self.pyramid_max,
            "allow_shorting": self.allow_shorting,
            "intraday_squareoff": self.intraday_squareoff,
            "squareoff_time_str": self.squareoff_time_str,
            "kill_switch": self.kill_switch,
            "daily_loss_reset_time_str": self.daily_loss_reset_time_str,
            "lot_size": self.lot_size,
            "market_open_str": self.market_open_str,
            "market_close_str": self.market_close_str,
        }
