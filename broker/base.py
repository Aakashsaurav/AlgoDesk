"""
broker/base.py
==============
Broker-agnostic interface for AlgoDesk.

This module defines the common contract that every broker implementation
must satisfy.  Phase 1 uses Upstox, but the rest of the system should only
depend on this base interface so the broker can be swapped later without
touching strategy or engine code.

Balance semantics:
    - ``cash`` / ``available_cash`` are the amount the broker currently
      allows you to trade with.
    - ``equity`` is total account value, including unrealised PnL.
    - ``balance`` is an alias for ``available_cash`` because that is the
      field trading logic usually cares about when sizing orders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class BrokerError(RuntimeError):
    """Raised when a broker operation cannot be completed safely."""


class OrderSide(str, Enum):
    """Canonical order directions supported by AlgoDesk."""

    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"

    @classmethod
    def normalize(cls, value: str | "OrderSide") -> "OrderSide":
        """Convert a user-supplied side to a validated enum value."""
        if isinstance(value, cls):
            return value
        try:
            return cls(value.upper().strip())
        except Exception as exc:
            raise ValueError(
                f"Invalid order side: {value!r}. "
                f"Expected one of: {[item.value for item in cls]}"
            ) from exc


class OrderStatus(str, Enum):
    """Broker order lifecycle states."""

    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(slots=True)
class OrderRequest:
    """
    Generic broker order request.

    The object is intentionally simple so it can map cleanly to Upstox,
    paper trading, or any future broker API.
    """

    symbol: str
    side: str | OrderSide
    quantity: int
    instrument_key: str = ""
    order_type: str = "MARKET"
    product: str = "MIS"
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    validity: str = "DAY"
    tag: str = ""
    client_order_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()
        self.side = OrderSide.normalize(self.side).value
        self.order_type = self.order_type.strip().upper()
        self.product = self.product.strip().upper()
        self.validity = self.validity.strip().upper()
        self.tag = self.tag.strip()
        self.client_order_id = self.client_order_id.strip()

        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.order_type not in {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}:
            raise ValueError(f"Unsupported order_type: {self.order_type!r}")
        if self.price is not None and self.price <= 0:
            raise ValueError(f"price must be > 0 when provided, got {self.price}")
        if self.trigger_price is not None and self.trigger_price <= 0:
            raise ValueError(
                f"trigger_price must be > 0 when provided, got {self.trigger_price}"
            )

    @property
    def is_exit(self) -> bool:
        """Return True for order sides that reduce or close exposure."""
        return self.side in {OrderSide.SELL.value, OrderSide.COVER.value}


@dataclass(slots=True)
class BrokerOrder:
    """
    Order snapshot returned by ``place_order`` and ``get_orders``.

    ``raw`` stores the broker-specific payload for debugging and audits.
    """

    order_id: str
    request: OrderRequest
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    average_fill_price: Optional[float] = None
    rejection_reason: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_quantity(self) -> int:
        """Quantity still open after partial fills."""
        return max(0, self.request.quantity - self.filled_quantity)


@dataclass(slots=True)
class BrokerPosition:
    """
    Canonical position snapshot for broker-independent portfolio reads.
    """

    symbol: str
    quantity: int
    average_price: float
    direction: int = 1
    instrument_key: str = ""
    product: str = "MIS"
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    market_price: Optional[float] = None
    opened_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.average_price <= 0:
            raise ValueError(
                f"average_price must be > 0, got {self.average_price}"
            )
        if self.direction not in (-1, 1):
            raise ValueError("direction must be +1 (long) or -1 (short)")
        self.product = self.product.strip().upper()

    @property
    def signed_quantity(self) -> int:
        """Quantity with direction applied."""
        return self.quantity * self.direction

    @property
    def market_value(self) -> float:
        """Current marked value if a market price is known."""
        price = self.market_price if self.market_price is not None else self.average_price
        return price * self.quantity

    @property
    def is_long(self) -> bool:
        return self.direction > 0

    @property
    def is_short(self) -> bool:
        return self.direction < 0


@dataclass(slots=True)
class AccountBalance:
    """
    Broker balance snapshot.

    ``balance`` is the amount most sizing logic should use.  It aliases
    ``available_cash`` so the meaning stays consistent across backtest and
    live trading.
    """

    cash: float
    available_cash: Optional[float] = None
    equity: Optional[float] = None
    margin_used: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    currency: str = "INR"
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cash = float(self.cash)
        self.available_cash = (
            float(self.cash) if self.available_cash is None else float(self.available_cash)
        )
        self.equity = (
            float(self.cash + self.unrealized_pnl - self.margin_used)
            if self.equity is None
            else float(self.equity)
        )
        self.margin_used = float(self.margin_used)
        self.unrealized_pnl = float(self.unrealized_pnl)
        self.realized_pnl = float(self.realized_pnl)
        self.currency = self.currency.strip().upper() or "INR"

    @property
    def balance(self) -> float:
        """Alias for available cash."""
        return float(self.available_cash)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the snapshot for logging or API responses."""
        return {
            "cash": self.cash,
            "available_cash": self.available_cash,
            "balance": self.balance,
            "equity": self.equity,
            "margin_used": self.margin_used,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "currency": self.currency,
            "updated_at": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }


class BrokerBase(ABC):
    """
    Abstract broker contract.

    Every broker implementation should expose the same public methods so
    the strategy layer and engine can stay broker-independent.
    """

    name: str = "generic-broker"

    @abstractmethod
    def connect(self) -> bool:
        """Open the broker session and return True when ready."""

    @abstractmethod
    def place_order(self, order: OrderRequest) -> Optional[BrokerOrder]:
        """
        Submit an order to the broker.

        Implementations should return a populated ``BrokerOrder`` on success
        or ``None`` when the order could not be accepted safely.
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a previously placed order. Return True on success."""

    @abstractmethod
    def get_positions(self) -> Sequence[BrokerPosition]:
        """Return all open positions known to the broker."""

    @abstractmethod
    def get_balance(self) -> AccountBalance:
        """Return the current account balance snapshot."""

    @abstractmethod
    def get_orders(self) -> Sequence[BrokerOrder]:
        """Return the current order book snapshot."""

    def safe_balance(self) -> float:
        """
        Convenience helper for sizing logic.

        Returns 0.0 if a broker returns an invalid balance snapshot instead
        of crashing the caller.
        """
        try:
            return float(self.get_balance().balance)
        except Exception:
            return 0.0


__all__ = [
    "AccountBalance",
    "BrokerBase",
    "BrokerError",
    "BrokerOrder",
    "BrokerPosition",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
]
