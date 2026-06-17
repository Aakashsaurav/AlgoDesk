"""
risk/position_sizer.py
-----------------------
Unified position sizing used by both backtester and live bot.
"""

from __future__ import annotations

import math
import logging
from enum import Enum
from typing import Optional

from risk.config import RiskConfig

logger = logging.getLogger(__name__)


class SizingMethod(str, Enum):
    FIXED_QUANTITY = "FIXED_QUANTITY"
    RISK_BASED = "RISK_BASED"
    FIXED_PCT_CAPITAL = "FIXED_PCT_CAPITAL"
    ATR_BASED = "ATR_BASED"


def compute_quantity(
    cash: float,
    entry_price: float,
    capital_risk_pct: float,
    fixed_quantity: int = 0,
    stop_price: Optional[float] = None,
    atr: Optional[float] = None,
    atr_mult: float = 2.0,
    lot_size: int = 1,
) -> int:
    """
    Calculate how many shares to buy/sell for one trade.
    Kept for backward compatibility with the backtester.
    """
    if entry_price <= 0 or cash <= 0:
        return 0

    if fixed_quantity > 0:
        cost = entry_price * fixed_quantity
        if cost > cash:
            affordable = int(cash / entry_price)
            return max(0, (affordable // lot_size) * lot_size if lot_size > 1 else affordable)
        return (fixed_quantity // lot_size) * lot_size if lot_size > 1 else fixed_quantity

    risk_rupees = cash * capital_risk_pct
    stop_distance: Optional[float] = None

    if stop_price is not None and stop_price > 0:
        stop_distance = abs(entry_price - stop_price)
    elif atr is not None and atr > 0:
        stop_distance = atr * atr_mult

    if stop_distance and stop_distance > 0:
        qty = int(math.floor(risk_rupees / stop_distance))
    else:
        qty = int(math.floor(cash * capital_risk_pct / entry_price))

    if qty <= 0:
        return 0

    max_affordable = int(math.floor(cash / entry_price))
    qty = min(qty, max_affordable)
    
    qty = (qty // lot_size) * lot_size
    return max(0, qty)


def compute_live_quantity(
    price: float,
    stop_loss: Optional[float],
    portfolio_value: float,
    risk_pct: float,
    lot_size: int = 1,
) -> int:
    """
    Calculate position size using the fixed-fractional risk model.
    Used primarily by the live bot.
    """
    if price <= 0 or portfolio_value <= 0:
        return lot_size

    risk_amount = portfolio_value * (risk_pct / 100.0)

    if stop_loss is not None and stop_loss > 0:
        risk_per_share = abs(price - stop_loss)
    else:
        risk_per_share = price * 0.02  # Default: 2% of price

    if risk_per_share <= 0:
        return lot_size

    qty = int(risk_amount / risk_per_share)
    
    if lot_size > 1:
        qty = (qty // lot_size) * lot_size

    qty = max(lot_size, qty)
    return qty


class PositionSizer:
    def __init__(self, method: SizingMethod, config: RiskConfig):
        self.method = method
        self.config = config

    def size(
        self,
        price: float,
        cash: float,
        atr: Optional[float] = None,
        stop_loss: Optional[float] = None,
        fixed_quantity: int = 0,
    ) -> int:
        if price <= 0 or cash <= 0:
            return 0

        qty = 0
        lot_size = max(1, self.config.lot_size)

        if self.method == SizingMethod.FIXED_QUANTITY:
            qty = fixed_quantity
        elif self.method == SizingMethod.FIXED_PCT_CAPITAL:
            alloc = cash * (self.config.max_position_size_pct / 100.0)
            qty = int(alloc / price)
        elif self.method == SizingMethod.RISK_BASED:
            risk_amt = cash * (self.config.max_daily_loss_pct / 100.0) # simplify risk to max daily, or specific config
            # Actually typically risk-based uses 1-2%. Since config lacks risk_per_trade_pct, we use a default of 2% or stop distance.
            dist = abs(price - stop_loss) if (stop_loss and stop_loss > 0) else (price * 0.02)
            if dist > 0:
                qty = int(risk_amt / dist)
        elif self.method == SizingMethod.ATR_BASED:
            risk_amt = cash * (self.config.max_daily_loss_pct / 100.0)
            dist = atr * 2.0 if atr else (price * 0.02)
            if dist > 0:
                qty = int(risk_amt / dist)

        # Cap by cash and max_position_size_pct
        max_alloc = min(cash, cash * (self.config.max_position_size_pct / 100.0))
        max_affordable = int(max_alloc / price)
        qty = min(qty, max_affordable)

        # Round down to lot size
        if lot_size > 1:
            qty = (qty // lot_size) * lot_size
            
        return max(0, qty)
