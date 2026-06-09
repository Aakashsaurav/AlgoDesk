# Use cases:
# - Encapsulate tunable risk limits (daily loss, max positions).
# - Share the same structure between the risk guard and configuration sources.
"""
risk/config.py
--------------
Configuration helpers for the standalone risk engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RiskConfig:
    """
    Risk limits enforced by the risk engine.
    """

    initial_capital: float = 500_000.0
    max_daily_loss_pct: float = 0.10
    max_positions: int = 10
    allow_shorting: bool = True
