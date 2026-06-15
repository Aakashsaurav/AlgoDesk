# Use cases:
# - Stable public API for the standalone backtester module.
# - Single import surface for engine, config, optimizer, reporting, and data feed.
"""
backtester — AlgoDesk Backtesting Engine
=========================================

Public API::

    from backtester import BacktestEngine, BacktestConfig, OrderType
    from backtester import Optimizer, SearchMethod, BacktestResult

All implementation lives in sub-modules.  Only these names are considered
part of the stable public API.  Everything else is subject to change.
"""

from backtester.models import (
    BacktestConfig,
    BacktestResult,
    Position,
    Trade,
    OrderType,
    TrailingType,
    PortfolioResult,
)
from backtester.datafeed import BacktestDataFeed
from backtester.engine import BacktestEngine
from backtester.optimizer import Optimizer, SearchMethod, ExecutorMode
from backtester.performance import compute_performance
from backtester.report import generate_report
from backtester.exporter import BacktestExporter
from backtester.commission import (
    IndianEquityCommission,
    CommissionBase,
    ZeroCommission,
)

__all__ = [
    "BacktestEngine",
    "BacktestDataFeed",
    "BacktestConfig",
    "BacktestResult",
    "PortfolioResult",
    "Position",
    "Trade",
    "OrderType",
    "TrailingType",
    "Optimizer",
    "SearchMethod",
    "ExecutorMode",
    "compute_performance",
    "generate_report",
    "BacktestExporter",
    "IndianEquityCommission",
    "CommissionBase",
    "ZeroCommission",
]
