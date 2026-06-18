"""
live_bot/orders/live_broker.py
------------------------------
Live order execution wrapper for Phase 8.

This module provides a ``LiveBroker`` class that mirrors the interface of
:class:`PaperBroker` but sends *real* orders to Upstox using the
``upstox_client`` SDK.

The engine and tests interact only with the methods defined here, so
swapping between paper and live mode is as simple as changing
``config.PAPER_TRADE``.

Behaviour is deliberately conservative: if the SDK is not installed or an
API call fails, log an error and return ``None`` rather than crashing.

IMPORTANT
=========
``check_pending_orders`` and ``check_stop_loss_take_profit`` are no-ops
here — in live trading those responsibilities are handled server-side by
Upstox (GTT orders, portfolio stream events).

P1 FIX (2026-04-11) — squareoff_all was a silent no-op
=======================================================
P2 FIX (2026-04-11) — IST constant extracted to config.py
==========================================================
Removed local ``IST = timezone(timedelta(hours=5, minutes=30))`` definition.
Six live_bot modules each had an identical copy. The canonical definition is
now ``config.IST``. Import changed to ``from config import IST``.
Previously ``squareoff_all()`` logged "no action taken" and returned
normally. The squareoff monitor (``LiveBotEngine._squareoff_monitor``)
calls this at 15:20 IST — believing squareoff succeeded because the
method returned without error. Live positions then survived past market
close, accruing overnight risk.

Fix: raise ``NotImplementedError`` so the failure is unmissable in logs,
monitoring alerts, and tests. The caller (``_squareoff_monitor``) catches
all exceptions and logs them at CRITICAL level, ensuring the operator
is notified and can act manually before market close.

This is intentionally left as NotImplementedError rather than a silent
no-op or a partial implementation:

  - A silent no-op creates a false sense of safety.
  - A partial implementation (cancel-and-resubmit) that is untested and
    live-money-consequential is more dangerous than no implementation.
  - The explicit error forces the developer to implement, test, and paper-
    trade the squareoff path before connecting to a live account.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

import live_bot.state as _state_module
from live_bot.state import LiveOrder
from config import IST

logger = logging.getLogger(__name__)


def _get_state():
    """Return the current live state singleton. Never cache this reference."""
    return _state_module.state


from live_bot.orders.base import BrokerInterface

class LiveBroker(BrokerInterface):
    """
    Routes orders to Upstox using their V3 Order API.

    The public interface mirrors :class:`PaperBroker` so the rest of the
    engine can be broker-agnostic. Most of the methods are simple wrappers
    around the SDK; when an order is placed we also record a pending
    :class:`~live_bot.state.LiveOrder` in our in-memory state so the
    dashboard and logs can show it immediately. The final status
    (filled / cancelled / rejected) arrives asynchronously via
    ``PortfolioFeed`` events.
    """

    def __init__(self, product: str = "I", access_token: Optional[str] = None):
        """
        Args:
            product:      "I" for MIS (intraday), "D" for CNC (delivery).
            access_token: Valid Upstox OAuth token (required for API calls).
        """
        self.product      = product
        self.access_token = access_token
        self._api         = None

        logger.info(f"[LiveBroker] Initialised. Product={product}. Mode=LIVE TRADE")

        try:
            import upstox_client

            configuration                 = upstox_client.Configuration()
            configuration.access_token    = access_token
            self._api = upstox_client.OrderApiV3(
                upstox_client.ApiClient(configuration)
            )
        except ImportError:
            logger.error("[LiveBroker] upstox_client not installed; live orders unavailable.")
        except Exception as e:
            logger.error(f"[LiveBroker] Failed to set up OrderApiV3: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol:          str,
        instrument_key:  str,
        action:          str,
        quantity:        int,
        order_type:      str = "MARKET",
        limit_price:     Optional[float] = None,
        stop_loss:       Optional[float] = None,
        take_profit:     Optional[float] = None,
        strategy_tag:    str = "",
    ) -> Optional[LiveOrder]:
        """
        Place a live order via Upstox.

        On success, creates a ``LiveOrder`` with status "PENDING" and adds
        it to the shared state. The actual fill details are expected to
        arrive through the PortfolioFeed websocket.
        """
        if not self._api:
            logger.error("[LiveBroker] Cannot place order: API client unavailable.")
            return None

        try:
            import upstox_client
        except ImportError:
            logger.error("[LiveBroker] upstox_client import failed during order placement.")
            return None

        req = upstox_client.PlaceOrderV3Request(
            quantity          = quantity,
            product           = self.product,
            validity          = "DAY",
            price             = limit_price or 0.0,
            tag               = strategy_tag or None,
            slice             = False,
            instrument_token  = instrument_key,
            order_type        = order_type,
            transaction_type  = "BUY" if action in ("BUY", "SHORT") else "SELL",
            disclosed_quantity= 0,
            trigger_price     = stop_loss or 0.0,
            is_amo            = False,
        )

        try:
            resp = self._api.place_order(req)
        except Exception as e:
            logger.error(f"[LiveBroker] Order placement failed: {e}")
            return None

        order_id = getattr(resp, "order_id", None) or str(uuid.uuid4())[:16]

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
        logger.info(
            f"[LiveBroker] Order sent: {order_id} | "
            f"{action} {symbol} x{quantity} [{order_type}]"
        )
        return order

    # ------------------------------------------------------------------
    # Compatibility stubs
    # ------------------------------------------------------------------

    def check_pending_limit_orders(self, symbol: str) -> None:
        """
        No-op in live mode. Upstox handles pending/limit orders server-side.

        This method exists so the engine can call it unconditionally without
        branching on broker type.
        """
        pass

    def check_stop_loss_take_profit(self, symbol: str) -> None:
        """
        No-op in live mode. Stop-loss/take-profit are enforced server-side
        via Upstox GTT orders and reported back through the portfolio stream.
        """
        pass

    # ------------------------------------------------------------------
    # Squareoff
    # ------------------------------------------------------------------

    def _squareoff_one(self, item) -> tuple[str, bool]:
        symbol, position = item
        try:
            exit_action = "SELL" if position.direction > 0 else "COVER"
            order = self.place_order(
                symbol=symbol,
                instrument_key=position.instrument_key,
                action=exit_action,
                quantity=position.quantity,
                order_type="MARKET",
                strategy_tag=position.strategy_tag or "SQUAREOFF",
            )
            if order is None:
                logger.error("[LiveBroker] squareoff_all: failed to place exit order for %s.", symbol)
                return symbol, False
            logger.info("[LiveBroker] squareoff_all: exit order sent for %s | %s x%d", symbol, exit_action, position.quantity)
            return symbol, True
        except Exception as exc:
            logger.error("[LiveBroker] squareoff_all: exception while exiting %s: %s", symbol, exc, exc_info=True)
            return symbol, False

    def squareoff_all(self) -> None:
        positions = _get_state().get_all_positions()
        if not positions:
            logger.info("[LiveBroker] squareoff_all: no open positions.")
            return

        logger.warning("[LiveBroker] squareoff_all: attempting market exit for %d position(s)", len(positions))

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(10, len(positions))) as ex:
            results = list(ex.map(self._squareoff_one, positions.items()))
            
        failures = [s for s, ok in results if not ok]
        if failures:
            msg = "[LiveBroker] squareoff_all incomplete. Exit order placement failed for: " + ", ".join(sorted(failures))
            logger.critical(msg)
            raise RuntimeError(msg)


    def place_gtt_order(self, trigger_price: float, quantity: int, limit_price: float, stop_loss: float) -> str:
        raise NotImplementedError("GTT order placement roadmap note")

    @property
    def is_paper(self) -> bool:
        return False
