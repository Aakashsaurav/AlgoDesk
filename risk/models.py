"""
risk/models.py
--------------
Shared data contracts used by both RiskEngine and RiskGuard.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List

from config import IST_TZ
from risk.config import RiskConfig


class RiskCheckCode(str, Enum):
    OK                  = "OK"
    KILL_SWITCH         = "KILL_SWITCH"
    MARKET_CLOSED       = "MARKET_CLOSED"
    SQUAREOFF_TIME      = "SQUAREOFF_TIME"
    INSUFFICIENT_CASH   = "INSUFFICIENT_CASH"
    DAILY_LOSS_LIMIT    = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN        = "MAX_DRAWDOWN"
    SHORT_NOT_ALLOWED   = "SHORT_NOT_ALLOWED"
    DUPLICATE_LONG      = "DUPLICATE_LONG"
    DUPLICATE_SHORT     = "DUPLICATE_SHORT"
    MAX_POSITIONS       = "MAX_POSITIONS"
    MAX_POSITION_SIZE   = "MAX_POSITION_SIZE"
    HOLIDAY             = "HOLIDAY"
    HALTED              = "HALTED"


@dataclass(slots=True)
class RiskCheckResult:
    allowed: bool
    code: RiskCheckCode
    reason: str
    checked_at: datetime

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def __bool__(self) -> bool:
        return self.allowed

    @classmethod
    def ok(cls) -> "RiskCheckResult":
        return cls(
            allowed=True,
            code=RiskCheckCode.OK,
            reason="",
            checked_at=datetime.now(tz=IST_TZ)
        )

    @classmethod
    def block(cls, code: RiskCheckCode, reason: str) -> "RiskCheckResult":
        return cls(
            allowed=False,
            code=code,
            reason=reason,
            checked_at=datetime.now(tz=IST_TZ)
        )


@dataclass
class RiskState:
    peak_equity: float = 0.0
    daily_realized_loss: float = 0.0    # sum of LOSING trades only
    daily_net_pnl: float = 0.0          # sum of all trades (net)
    trades_today: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(tz=IST_TZ))
    halted: bool = False
    halt_reason: str = ""
    kill_switch_active: bool = False


@dataclass(slots=True)
class RiskEvent:
    timestamp: datetime
    event_type: str        # "HALT", "KILL_SWITCH", "ORDER_BLOCKED", "ORDER_ALLOWED"
    symbol: str
    action: str
    code: RiskCheckCode
    reason: str
    portfolio_value: float


@dataclass
class RiskReport:
    config: RiskConfig
    state: RiskState
    events: List[RiskEvent]
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=IST_TZ))

    def summary(self) -> str:
        status = "HALTED" if self.state.halted else "ACTIVE"
        if self.state.kill_switch_active:
            status = "KILL_SWITCH_ENGAGED"
        
        return (
            f"--- Risk Report [{self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}] ---\n"
            f"Status: {status}\n"
            f"Peak Equity: {self.state.peak_equity:.2f}\n"
            f"Daily Realized Loss: {self.state.daily_realized_loss:.2f}\n"
            f"Daily Net PnL: {self.state.daily_net_pnl:.2f}\n"
            f"Trades Today: {self.state.trades_today}\n"
            f"Events Recorded: {len(self.events)}\n"
        )

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "state": asdict(self.state),
            "events": [asdict(e) for e in self.events],
            "generated_at": self.generated_at.isoformat()
        }
