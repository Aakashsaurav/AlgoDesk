"""
risk/base.py
------------
Abstract Base Contract for Risk Engine.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

from risk.config import RiskConfig
from risk.models import RiskState, RiskEvent, RiskReport, RiskCheckResult, RiskCheckCode


class RiskEngineBase(ABC):
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.state = RiskState(peak_equity=config.initial_capital)
        self._events: list[RiskEvent] = []
        self._logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def check_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        cash: float,
        open_positions: Dict[str, Any],
    ) -> RiskCheckResult:
        """
        Check if an order satisfies all risk constraints.
        Returns a RiskCheckResult.
        """
        ...

    @abstractmethod
    def record_equity(self, equity: float) -> None:
        """Record current equity to track drawdown."""
        ...

    @abstractmethod
    def record_trade(self, pnl: float, is_loss: bool = False) -> None:
        """Record trade results to track daily loss and limits."""
        ...

    def can_open(self, current_positions: int, direction: int) -> bool:
        """
        Simplified check for backtester event loop.
        Delegates basic checks to check_order with dummy values where possible.
        """
        if self.state.halted or self.state.kill_switch_active:
            return False
            
        action = "BUY" if direction == 1 else "SELL"
        
        # Simple shorting check
        if direction == -1 and not self.config.allow_shorting:
            return False
            
        # Max positions check
        if current_positions >= self.config.max_positions:
            return False
            
        return True

    def get_report(self) -> RiskReport:
        return RiskReport(
            config=self.config,
            state=self.state,
            events=self._events.copy()
        )

    def reset(self) -> None:
        self.state = RiskState(peak_equity=self.config.initial_capital)
        self._events.clear()
        self._logger.info("RiskEngine state reset to initial config.")

    def activate_kill_switch(self, reason: str = "") -> None:
        self.state.kill_switch_active = True
        self.state.halted = True
        self.state.halt_reason = f"Kill switch activated: {reason}"
        self._logger.warning(self.state.halt_reason)

    def is_halted(self) -> bool:
        return self.state.halted or self.state.kill_switch_active
