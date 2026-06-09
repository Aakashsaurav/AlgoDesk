# Use cases:
# - Preserve older imports that expect `strategies.base_strategy_github`.
# - Keep one canonical implementation in `strategies.base`.
"""
strategies/base_strategy_github.py
====================================
Backward-compatibility alias.

All code that previously imported from this file continues to work.
The canonical source is now strategies/base.py.
"""
from strategies.base import (
    BaseStrategy,
    Signal,
    Action,
    OrderType,
    PortfolioState,
    MIN_WARMUP_BARS,
)

__all__ = [
    "BaseStrategy", "Signal", "Action", "OrderType", "PortfolioState", "MIN_WARMUP_BARS"
]
