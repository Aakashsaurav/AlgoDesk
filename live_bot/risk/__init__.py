"""
live_bot/risk/__init__.py
Backward-compatibility shim. Import from risk instead.
"""
import warnings

warnings.warn(
    "live_bot.risk is deprecated. Use risk instead.",
    DeprecationWarning, stacklevel=2,
)

from risk.guard import LiveRiskGuard as RiskGuard
from risk.position_sizer import compute_live_quantity

__all__ = ["RiskGuard", "compute_live_quantity"]