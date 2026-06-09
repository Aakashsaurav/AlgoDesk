# Use cases:
# - Expose the standalone screener API for imports elsewhere.
# - Keep a minimal namespace so the CLI or dashboard can import quickly.
"""
screener package exports.
"""

from screener.base import ScreenResult, ScreenerConfig, ScreenRule
from screener.engine import ScreenerEngine
from screener.rules import GoldenCrossRule, RSIRule
from screener.strategy_screener import StrategyScreener, StrategyScreenerConfig

__all__ = [
    "ScreenResult",
    "ScreenerConfig",
    "ScreenRule",
    "ScreenerEngine",
    "GoldenCrossRule",
    "RSIRule",
    "StrategyScreener",
    "StrategyScreenerConfig",
]
