"""Backward-compatibility shim. Import from risk.guard instead."""
import warnings
warnings.warn(
    "live_bot.risk.risk_guard is deprecated. Use risk.guard.LiveRiskGuard.",
    DeprecationWarning, stacklevel=2,
)
from risk.guard import LiveRiskGuard as RiskGuard
__all__ = ["RiskGuard"]