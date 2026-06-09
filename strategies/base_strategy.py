# Use cases:
# - Preserve older imports that expect `strategies.base_strategy`.
# - Keep one canonical implementation in `strategies.base`.
"""
strategies/base_strategy.py
---------------------------
Backward-compatible alias to the canonical strategy base module.
"""

from strategies.base import (
    Action,
    BaseStrategy,
    DEFAULT_SYMBOL,
    MIN_WARMUP_BARS,
    OrderType,
    PortfolioState,
    Signal,
    StrategyMetadata,
)

__all__ = [
    "Action",
    "BaseStrategy",
    "DEFAULT_SYMBOL",
    "MIN_WARMUP_BARS",
    "OrderType",
    "PortfolioState",
    "Signal",
    "StrategyMetadata",
]
