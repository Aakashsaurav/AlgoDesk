# Use cases:
# - Enforce max position count and daily loss limits independently from execution.
# - Expose a single entry point for both backtest and live risk checks.
# - Offer simple hooks for the event loop to call pre-order and post-trade.
"""
risk/engine.py
---------------
Standalone risk guard enforcing configurable loss and exposure limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from risk.config import RiskConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskState:
    daily_loss: float = 0.0
    last_reset: datetime = datetime.utcnow()
    halted: bool = False


class RiskEngine:
    """
    Risk engine enforcing daily drawdowns and max position constraints.
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.state = RiskState()
        self.peak_equity = config.initial_capital

    def reset(self) -> None:
        self.state = RiskState()
        self.peak_equity = self.config.initial_capital

    def record_equity(self, equity: float) -> None:
        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown = (equity - self.peak_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if drawdown <= -self.config.max_daily_loss_pct:  # P3 FIX: was < (off-by-epsilon boundary bug)
            self.state.halted = True
            logger.warning("RiskEngine: drawdown limit reached (%.2f%%)", drawdown * 100)

    def record_trade(self, pnl: float) -> None:
        self.state.daily_loss += pnl
        if self.state.daily_loss <= -self.config.initial_capital * self.config.max_daily_loss_pct:  # P3 FIX: was < (same boundary fix)
            self.state.halted = True
            logger.warning(
                "RiskEngine: daily loss limit breached — current loss ₹%.2f",
                abs(self.state.daily_loss),
            )

    def can_open(self, current_positions: int, direction: int) -> bool:
        if self.state.halted:
            return False
        if current_positions >= self.config.max_positions:
            logger.debug("RiskEngine: max positions (%s) reached.", self.config.max_positions)
            return False
        if direction < 0 and not self.config.allow_shorting:
            logger.debug("RiskEngine: shorting disabled.")
            return False
        return True