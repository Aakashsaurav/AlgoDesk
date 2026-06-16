# Use cases:
# - Provide stable package-level imports for the strategy layer.
# - Expose registry and base types to the dashboard, backtester, and tests.
"""
strategies package exports.
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
    ParamSpec,
    StrategyMode,
    StrategyScope,
)
from strategies.registry import (
    StrategyRegistryError,
    get_strategy_registry,
    get_strategy_schema,
    get_registry_diagnostics,
    list_strategies,
    list_by_category,
    load_strategy,
    get_strategy_class,
    validate_strategy_input,
    format_strategy_table,
    strategy_registry_to_json,
    generate_strategy_docs,
)
from strategies.day_strategy.orb_nifty import OpeningRangeBreakoutStrategy, ORBNiftyStrategy
from strategies.categories import StrategyCategory
from strategies.utils import (
    long_only_state_signals,
    long_short_state_signals,
    suppress_warmup,
    first_signal_per_session,
    require_datetime_index,
    session_dates,
    time_mask,
    set_signal,
    copy_ohlcv,
    validate_no_lookahead_columns,
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
    "get_strategy_registry",
    "get_strategy_schema",
    "get_registry_diagnostics",
    "list_strategies",
    "list_by_category",
    "load_strategy",
    "get_strategy_class",
    "OpeningRangeBreakoutStrategy",
    "ORBNiftyStrategy",
    "validate_strategy_input",
    "format_strategy_table",
    "strategy_registry_to_json",
    "generate_strategy_docs",
    "StrategyCategory",
    "ParamSpec",
    "StrategyMode",
    "StrategyScope",
    "StrategyRegistryError",
    "long_only_state_signals",
    "long_short_state_signals",
    "suppress_warmup",
    "first_signal_per_session",
    "require_datetime_index",
    "session_dates",
    "time_mask",
    "set_signal",
    "copy_ohlcv",
    "validate_no_lookahead_columns",
]
