# Use cases:
# - Package-level exports for trend strategies.
# - Stable imports for registry, tests, and external modules.
"""Trend strategy exports."""

from strategies.trend.supertrend_strategy import SupertrendStrategy

__all__ = ["SupertrendStrategy"]
