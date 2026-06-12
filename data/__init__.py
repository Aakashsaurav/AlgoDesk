"""
data — AlgoDesk data layer package.

Provides a broker-agnostic data acquisition, caching, validation, and
universe management framework.

Public API
----------
DataProviderBase     : ABC that all data providers must implement.
DataManager          : Unified cache / fetch / resample orchestrator.
DataValidator        : OHLCV quality checks and auto-cleaning.
UniverseManager      : Stock-universe lookups (Nifty 50/100/200/500, custom).
SymbolMapper         : Cross-provider symbol normalisation.
TokenBucketRateLimiter : Thread-safe token-bucket rate limiter.
CompositeRateLimiter : Multi-bucket rate limiter for APIs with layered limits.

Usage
-----
    from data import DataManager, DataProviderBase
    from data.providers.yfinance_provider import YFinanceProvider

    provider = YFinanceProvider()
    mgr = DataManager(provider=provider)
    df = mgr.fetch("RELIANCE", interval="daily")
"""

from __future__ import annotations

# Lazy imports to avoid heavy dependency loading on ``import data``.
# Concrete classes are imported on first access via __getattr__.

__all__: list[str] = [
    "DataProviderBase",
    "DataManager",
    "DataValidator",
    "UniverseManager",
    "SymbolMapper",
    "TokenBucketRateLimiter",
    "CompositeRateLimiter",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "DataProviderBase":       ("data.base",         "DataProviderBase"),
    "DataManager":            ("data.manager",       "DataManager"),
    "DataValidator":          ("data.validator",      "DataValidator"),
    "UniverseManager":        ("data.universe",       "UniverseManager"),
    "SymbolMapper":           ("data.universe",       "SymbolMapper"),
    "TokenBucketRateLimiter": ("data.rate_limiter",   "TokenBucketRateLimiter"),
    "CompositeRateLimiter":   ("data.rate_limiter",   "CompositeRateLimiter"),
}


def __getattr__(name: str):  # noqa: N807
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module 'data' has no attribute {name!r}")
