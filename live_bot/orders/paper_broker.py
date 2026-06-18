import logging
import uuid
from datetime import datetime
from typing import Optional

from config import IST

import live_bot.state as _state_module
from live_bot.state import (
    LiveOrder,
    LivePosition,
    ClosedTrade,
)
from live_bot.orders.base import BrokerInterface
from backtester.commission import IndianEquityCommission, Segment

def _get_state():
    return _state_module.state

logger = logging.getLogger(__name__)

SLIPPAGE_PCT = 0.0005   # 0.05%

_COMMISSION = IndianEquityCommission()

def _compute_slippage(price: float, action: str) -> float:
    if action in ("BUY", "SHORT"):
        return round(price * (1 + SLIPPAGE_PCT), 2)
    else:
        return round(price * (1 - SLIPPAGE_PCT), 2)

def _compute_commission(price: float, quantity: int, product: str = "I") -> float:
    segment = Segment.EQUITY_INTRADAY if product == "I" else Segment.EQUITY_DELIVERY
    breakdown = _COMMISSION.calculate("BUY", quantity, price, segment.value)
    return breakdown.total

class PaperBroker(BrokerInterface):
    def __init__(self, product: str = "I"):
        self.product = product
        logger.info(f"[PaperBroker] Initialised. Product={product}. Mode=PAPER TRADE")

    @property
    def is_paper(self) -> bool:
        return True

    def place_order(
        self,
        symbol:          str,
        instrument_key:  str,
        action:          str,          # "BUY", "SELL", "SHORT", "COVER"
        quantity:        int,
        order_type:      str = "MARKET",
        limit_price:     Optional[float] = None,
        stop_loss:       Optional[float] = None,
        take_profit:     Optional[float] = None,
        strategy_tag:    str = "",
    ) -> Optional[LiveOrder]:
        tick = _get_state().get_tick(symbol)
        current_ltp = tick.ltp if tick else 0.0

        if current_ltp <= 0:
            logger.warning(f"[PaperBroker] Rejecting {action} {symbol}: No price data available.")
            _get_state().log_activity("ORDER_REJECTED", f"Order rejected: {symbol} {action} — no price data.", level="WARNING")
            return None

        if action in ("SELL", "COVER"):
            position = _get_state().get_position(symbol)
            if position is None:
                logger.warning(f"[PaperBroker] Rejecting {action} {symbol}: No open position.")
                _get_state().log_activity("ORDER_REJECTED", f"Order rejected: {symbol} {action} — no open position.", level="WARNING")
                return None
            if quantity > position.quantity:
                quantity = position.quantity

        order_id = str(uuid.uuid4())[:16]

        order = LiveOrder(
            order_id       = order_id,
            symbol         = symbol,
            instrument_key = instrument_key,
            action         = action,
            quantity       = quantity,
            order_type     = order_type,
            limit_price    = limit_price,
            status         = "PENDING",
            created_at     = datetime.now(tz=IST),
            strategy_tag   = strategy_tag,
        )

        _get_state().add_order(order)
        
        if order_type == "MARKET":
            fill_price = _compute_slippage(current_ltp, action)
            # LB-B12: check if fill order succeeds
            filled_ok = self._fill_order(order, fill_price, stop_loss, take_profit)
            if not filled_ok:
                return None

        return order

    def check_pending_limit_orders(self, symbol: str) -> None:
        tick = _get_state().get_tick(symbol)
        if tick is None:
            return

        ltp = tick.ltp
        all_orders = _get_state().get_all_orders()

        for order_id, order in all_orders.items():
            if (
                order.symbol == symbol
                and order.status == "PENDING"
                and order.order_type == "LIMIT"
                and order.limit_price is not None
            ):
                should_fill = (
                    (order.action == "BUY"   and ltp <= order.limit_price) or
                    (order.action == "SELL"  and ltp >= order.limit_price) or
                    (order.action == "SHORT" and ltp >= order.limit_price) or
                    (order.action == "COVER" and ltp <= order.limit_price)
                )

                if should_fill:
                    fill_price = _compute_slippage(ltp, order.action)
                    position = _get_state().get_position(symbol)
                    sl = position.stop_loss   if position else None
                    tp = position.take_profit if position else None
                    self._fill_order(order, fill_price, sl, tp)

    def check_stop_loss_take_profit(self, symbol: str) -> None:
        tick     = _get_state().get_tick(symbol)
        position = _get_state().get_position(symbol)

        if tick is None or position is None:
            return

        ltp = tick.ltp

        if position.stop_loss is not None and position.stop_loss > 0:
            sl_hit = (
                (position.direction > 0 and ltp <= position.stop_loss) or
                (position.direction < 0 and ltp >= position.stop_loss)
            )
            if sl_hit:
                logger.warning(f"[PaperBroker] STOP LOSS HIT: {symbol} LTP={ltp:.2f} SL={position.stop_loss:.2f}")
                # Gap fill logic for SL/TP (LB-B23)
                fill_price = min(ltp, position.stop_loss) if position.direction > 0 else max(ltp, position.stop_loss)
                self._exit_position(symbol, fill_price, "STOP_LOSS")
                return

        if position.take_profit is not None and position.take_profit > 0:
            tp_hit = (
                (position.direction > 0 and ltp >= position.take_profit) or
                (position.direction < 0 and ltp <= position.take_profit)
            )
            if tp_hit:
                logger.info(f"[PaperBroker] TAKE PROFIT HIT: {symbol} LTP={ltp:.2f} TP={position.take_profit:.2f}")
                fill_price = max(ltp, position.take_profit) if position.direction > 0 else min(ltp, position.take_profit)
                self._exit_position(symbol, fill_price, "TAKE_PROFIT")

    def squareoff_all(self) -> None:
        positions = _get_state().get_all_positions()
        if not positions:
            logger.info("[PaperBroker] Squareoff: No open positions.")
            return

        logger.info(f"[PaperBroker] Squareoff: Closing {len(positions)} position(s).")
        for symbol in list(positions.keys()):
            tick = _get_state().get_tick(symbol)
            ltp  = tick.ltp if tick and tick.ltp > 0 else None
            if ltp:
                self._exit_position(symbol, ltp, "SQUAREOFF")
            else:
                logger.warning(f"[PaperBroker] Squareoff: No price for {symbol}. Cannot close position.")

    def _fill_order(
        self,
        order:       LiveOrder,
        fill_price:  float,
        stop_loss:   Optional[float],
        take_profit: Optional[float],
    ) -> bool:
        commission = _compute_commission(fill_price, order.quantity, self.product)

        _get_state().update_order_status(
            order_id   = order.order_id,
            status     = "FILLED",
            fill_price = fill_price,
            filled_at  = datetime.now(tz=IST),
        )

        logger.info(
            f"[PaperBroker] FILLED: {order.order_id} | "
            f"{order.action} {order.symbol} x{order.quantity} "
            f"@ ₹{fill_price:.2f} | Commission: ₹{commission:.2f}"
        )

        if order.action == "BUY":
            cost = fill_price * order.quantity + commission
            try:
                _get_state().debit_cash(cost)
            except ValueError as exc:
                logger.warning(f"[PaperBroker] Fill rejected for {order.symbol}: {exc}")
                _get_state().update_order_status(order.order_id, "REJECTED")
                _get_state().log_activity("ORDER_REJECTED", f"Fill rejected: {order.symbol} — {exc}", level="WARNING")
                return False

            position = LivePosition(
                symbol         = order.symbol,
                instrument_key = order.instrument_key,
                direction      = 1,
                quantity       = order.quantity,
                entry_price    = fill_price,
                entry_time     = datetime.now(tz=IST),
                stop_loss      = stop_loss,
                take_profit    = take_profit,
                entry_commission = commission,
            )
            _get_state().add_position(position)
            _get_state().log_activity("TRADE_ENTRY", f"📈 BUY {order.symbol} x{order.quantity} @ ₹{fill_price:.2f} | SL={stop_loss} TP={take_profit}")

        elif order.action in ("SELL", "COVER"):
            self._close_position_on_fill(order, fill_price, commission)

        elif order.action == "SHORT":
            proceeds = fill_price * order.quantity - commission
            _get_state().credit_cash(proceeds)

            position = LivePosition(
                symbol         = order.symbol,
                instrument_key = order.instrument_key,
                direction      = -1,
                quantity       = order.quantity,
                entry_price    = fill_price,
                entry_time     = datetime.now(tz=IST),
                stop_loss      = stop_loss,
                take_profit    = take_profit,
                entry_commission = commission,
            )
            _get_state().add_position(position)
            _get_state().log_activity("TRADE_ENTRY", f"📉 SHORT {order.symbol} x{order.quantity} @ ₹{fill_price:.2f}")

        return True

    def _close_position_on_fill(self, order: LiveOrder, fill_price: float, commission: float) -> None:
        position = _get_state().close_position(order.symbol)
        if position is None:
            logger.error(f"[PaperBroker] _close_position_on_fill: No position found for {order.symbol} during fill.")
            return

        exit_commission  = commission
        proceeds         = fill_price * order.quantity - exit_commission
        _get_state().credit_cash(proceeds)

        entry_commission = getattr(position, "entry_commission", 0.0)
        gross_pnl = (fill_price - position.entry_price) * order.quantity * position.direction
        pnl_net = gross_pnl - exit_commission - entry_commission
        pnl_pct = pnl_net / (position.entry_price * order.quantity) * 100 if position.entry_price > 0 else 0

        trade = ClosedTrade(
            symbol       = order.symbol,
            direction    = "LONG" if position.direction > 0 else "SHORT",
            quantity     = order.quantity,
            entry_price  = position.entry_price,
            exit_price   = fill_price,
            entry_time   = position.entry_time,
            exit_time    = datetime.now(tz=IST),
            pnl          = round(pnl_net, 2),
            pnl_pct      = round(pnl_pct, 2),
            strategy_tag = order.strategy_tag or position.strategy_tag,
            exit_reason  = "SIGNAL",
        )
        _get_state().record_closed_trade(trade)

        emoji = "✅" if pnl_net >= 0 else "🔴"
        _get_state().log_activity("TRADE_EXIT", f"{emoji} EXIT {order.symbol} x{order.quantity} @ ₹{fill_price:.2f} | P&L: ₹{pnl_net:+.2f} ({pnl_pct:+.2f}%)", level="INFO" if pnl_net >= 0 else "WARNING")

    def _exit_position(self, symbol: str, exit_price: float, reason: str) -> None:
        position = _get_state().get_position(symbol)
        if position is None:
            return

        action   = "SELL" if position.direction > 0 else "COVER"
        fill_px  = _compute_slippage(exit_price, action)

        exit_commission = _compute_commission(fill_px, position.quantity, self.product)
        proceeds        = fill_px * position.quantity - exit_commission
        _get_state().close_position(symbol)
        _get_state().credit_cash(proceeds)

        entry_commission = getattr(position, "entry_commission", 0.0)
        gross_pnl = (fill_px - position.entry_price) * position.quantity * position.direction
        pnl_net = gross_pnl - exit_commission - entry_commission
        pnl_pct = pnl_net / (position.entry_price * position.quantity) * 100 if position.entry_price > 0 else 0

        trade = ClosedTrade(
            symbol       = symbol,
            direction    = "LONG" if position.direction > 0 else "SHORT",
            quantity     = position.quantity,
            entry_price  = position.entry_price,
            exit_price   = fill_px,
            entry_time   = position.entry_time,
            exit_time    = datetime.now(tz=IST),
            pnl          = round(pnl_net, 2),
            pnl_pct      = round(pnl_pct, 2),
            strategy_tag = position.strategy_tag,
            exit_reason  = reason,
        )
        _get_state().record_closed_trade(trade)

        emoji = "✅" if pnl_net >= 0 else "🔴"
        _get_state().log_activity("TRADE_EXIT", f"{emoji} {reason}: {symbol} x{position.quantity} @ ₹{fill_px:.2f} | P&L: ₹{pnl_net:+.2f} ({pnl_pct:+.2f}%)", level="INFO" if pnl_net >= 0 else "WARNING")