"""
broker/upstox/broker.py
=======================
Phase 1 Upstox broker implementation.

This class is the concrete implementation of the broker base interface.
It is deliberately defensive:

* If the Upstox SDK is unavailable, it still exposes a usable local state
  surface so the rest of the codebase can import and test safely.
* If the SDK is present, it will build the client and try to use the live
  order/funds/portfolio endpoints.
* Order, position, and balance reads always fail soft and fall back to the
  last cached local snapshot rather than crashing the caller.

The class is broker-facing only. Strategy code should never import this
module directly.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from config import config

from broker.base import (
    AccountBalance,
    BrokerBase,
    BrokerOrder,
    BrokerPosition,
    BrokerError,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from broker.upstox.auth import auth_manager

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """Return dict or attribute values without raising."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_product(product: str) -> str:
    """
    Upstox uses short product codes. Accept the common aliases too.

    I -> intraday
    D -> delivery
    """
    value = (product or "").strip().upper()
    if value in {"I", "MIS", "INTRADAY", "DAY"}:
        return "I"
    if value in {"D", "CNC", "DELIVERY", "NRML", "POS", "POSITIONAL"}:
        return "D"
    raise ValueError(
        f"Unsupported product value: {product!r}. Expected MIS/CNC/INTRADAY/DELIVERY."
    )


def _status_from_value(value: Any) -> OrderStatus:
    """Best-effort conversion to OrderStatus."""
    if isinstance(value, OrderStatus):
        return value
    text = str(value or "").upper().strip()
    for status in OrderStatus:
        if status.value == text:
            return status
    return OrderStatus.PENDING


class UpstoxBroker(BrokerBase):
    """
    Concrete Upstox broker implementation.
    """

    name = "upstox"

    def __init__(
        self,
        product: str = "MIS",
        access_token: Optional[str] = None,
        initial_balance: Optional[float] = None,
    ) -> None:
        self.product = _normalize_product(product)
        self.access_token = access_token
        self._sdk = None
        self._connected = False

        starting_cash = (
            float(initial_balance)
            if initial_balance is not None
            else float(getattr(config, "TOTAL_CAPITAL", 500_000.0))
        )
        self._balance = AccountBalance(cash=starting_cash)
        self._orders: List[BrokerOrder] = []
        self._positions: Dict[str, BrokerPosition] = {}

        self._api_client = None
        self._order_api = None
        self._portfolio_api = None
        self._funds_api = None

    # ------------------------------------------------------------------
    # Connection / SDK bootstrap
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish an Upstox SDK session.

        Returns True only when the SDK is available and at least one live
        API client was created successfully.
        """
        if self._connected:
            return True

        sdk = self._load_sdk()
        if sdk is None:
            logger.warning(
                "Upstox SDK is not installed. Broker will stay in offline mode "
                "and return local snapshots only."
            )
            return False

        token = self.access_token
        if not token:
            try:
                token = auth_manager.get_valid_token()
            except Exception as exc:
                logger.warning("No valid Upstox token available: %s", exc)
                return False

        try:
            configuration = sdk.Configuration()
            configuration.access_token = token
            self._api_client = sdk.ApiClient(configuration)
        except Exception as exc:
            logger.error("Failed to build Upstox ApiClient: %s", exc, exc_info=True)
            return False

        self._order_api = self._build_api(
            sdk,
            ("OrderApiV3", "OrderApi"),
            self._api_client,
        )
        self._portfolio_api = self._build_api(
            sdk,
            ("PortfolioApiV2", "PortfolioApi"),
            self._api_client,
        )
        self._funds_api = self._build_api(
            sdk,
            ("FundApi", "FundsApi", "UserApi", "AccountApi"),
            self._api_client,
        )

        self._connected = any(
            api is not None for api in (self._order_api, self._portfolio_api, self._funds_api)
        )

        if self._connected:
            self._sdk = sdk
            self.access_token = token
            logger.info("Upstox broker connected successfully.")
        else:
            logger.warning(
                "Upstox SDK imported but no usable API classes were found. "
                "Broker remains offline."
            )
        return self._connected

    def _load_sdk(self):
        """Import upstox_client lazily so the module remains import-safe."""
        try:
            return importlib.import_module("upstox_client")
        except Exception:
            return None

    @staticmethod
    def _build_api(sdk: Any, class_names: Sequence[str], api_client: Any) -> Any:
        """Instantiate the first available SDK API class from class_names."""
        for name in class_names:
            api_cls = getattr(sdk, name, None)
            if api_cls is None:
                continue
            try:
                return api_cls(api_client)
            except Exception:
                logger.debug("Could not instantiate %s", name, exc_info=True)
        return None

    # ------------------------------------------------------------------
    # BrokerBase
    # ------------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> Optional[BrokerOrder]:
        """
        Submit an order to Upstox.

        If the live SDK path is unavailable, a rejected order is returned so
        callers can still inspect the failure reason.
        """
        try:
            if isinstance(order, OrderRequest):
                normalized_order = order
            elif isinstance(order, dict):
                normalized_order = OrderRequest(**order)
            else:
                normalized_order = OrderRequest(
                    symbol=str(_safe_get(order, "symbol", "")),
                    side=str(_safe_get(order, "side", "")),
                    quantity=int(_safe_get(order, "quantity", 0) or 0),
                    instrument_key=str(_safe_get(order, "instrument_key", "")),
                    order_type=str(_safe_get(order, "order_type", "MARKET")),
                    product=str(_safe_get(order, "product", "MIS")),
                    price=_safe_get(order, "price"),
                    trigger_price=_safe_get(order, "trigger_price"),
                    validity=str(_safe_get(order, "validity", "DAY")),
                    tag=str(_safe_get(order, "tag", "")),
                    client_order_id=str(_safe_get(order, "client_order_id", "")),
                    metadata=dict(_safe_get(order, "metadata", {}) or {}),
                )
            order = normalized_order
        except Exception as exc:
            logger.error("Invalid order request: %s", exc)
            return None

        if not self._connected and not self.connect():
            return self._reject_order(order, "Upstox broker is not connected")

        if self._sdk is None or self._order_api is None:
            return self._reject_order(order, "Upstox order API is unavailable")

        order_id = order.client_order_id or str(uuid.uuid4())[:16]
        payload = self._build_order_payload(order)
        response: Any = None

        try:
            response = self._invoke_with_payload(
                self._order_api,
                ("place_order", "place_order_v3", "submit_order"),
                payload,
            )
        except Exception as exc:
            logger.error("Upstox order placement failed: %s", exc, exc_info=True)
            return self._reject_order(order, str(exc), order_id=order_id)

        parsed = self._parse_order_response(order_id, order, response)
        self._orders.append(parsed)
        logger.info(
            "Order placed: %s %s x%s [%s] status=%s",
            parsed.request.side,
            parsed.request.symbol,
            parsed.request.quantity,
            parsed.request.order_type,
            parsed.status.value,
        )
        return parsed

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order, falling back to local cache if needed."""
        if not order_id:
            return False

        if self._connected and self._order_api is not None and self._sdk is not None:
            try:
                self._invoke_with_payload(
                    self._order_api,
                    ("cancel_order", "cancel_order_v3", "delete_order"),
                    order_id,
                )
            except Exception as exc:
                logger.warning("Remote order cancel failed for %s: %s", order_id, exc)
                # fall back to local bookkeeping below

        updated = False
        for idx, order in enumerate(self._orders):
            if order.order_id == order_id:
                self._orders[idx] = BrokerOrder(
                    order_id=order.order_id,
                    request=order.request,
                    status=OrderStatus.CANCELLED,
                    filled_quantity=order.filled_quantity,
                    average_fill_price=order.average_fill_price,
                    rejection_reason=order.rejection_reason,
                    created_at=order.created_at,
                    updated_at=_utc_now(),
                    raw=order.raw,
                )
                updated = True
                break
        return updated

    def get_positions(self) -> Sequence[BrokerPosition]:
        """
        Return the latest position snapshot.

        When the SDK is unavailable, returns the locally cached state.
        """
        remote = self._fetch_remote_positions()
        if remote is not None:
            self._positions = {p.symbol: p for p in remote}
        return list(self._positions.values())

    def get_balance(self) -> AccountBalance:
        """
        Return the latest balance snapshot.

        The local cached balance is used whenever the live broker cannot be
        queried safely.
        """
        remote = self._fetch_remote_balance()
        if remote is not None:
            self._balance = remote
        return self._balance

    def get_orders(self) -> Sequence[BrokerOrder]:
        """Return the latest known order snapshot."""
        remote = self._fetch_remote_orders()
        if remote is not None:
            self._orders = remote
        return list(self._orders)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Refresh all broker snapshots in one call."""
        self.get_balance()
        self.get_positions()
        self.get_orders()

    # ------------------------------------------------------------------
    # Internal parsing helpers
    # ------------------------------------------------------------------

    def _build_order_payload(self, order: OrderRequest) -> Any:
        """Create a request object or dictionary for the Upstox SDK."""
        if self._sdk is None:
            return order

        request_cls = getattr(self._sdk, "PlaceOrderV3Request", None)
        if request_cls is not None:
            try:
                return request_cls(
                    quantity=order.quantity,
                    product=self.product,
                    validity=order.validity,
                    price=float(order.price or 0.0),
                    tag=order.tag or None,
                    slice=False,
                    instrument_token=order.instrument_key or order.symbol,
                    order_type=order.order_type,
                    transaction_type="BUY" if order.side in {"BUY", "SHORT"} else "SELL",
                    disclosed_quantity=0,
                    trigger_price=float(order.trigger_price or 0.0),
                    is_amo=False,
                )
            except Exception:
                logger.debug("Could not build PlaceOrderV3Request", exc_info=True)

        # Dict fallback for SDK variants or tests.
        return {
            "quantity": order.quantity,
            "product": self.product,
            "validity": order.validity,
            "price": float(order.price or 0.0),
            "tag": order.tag or None,
            "slice": False,
            "instrument_token": order.instrument_key or order.symbol,
            "order_type": order.order_type,
            "transaction_type": "BUY" if order.side in {"BUY", "SHORT"} else "SELL",
            "disclosed_quantity": 0,
            "trigger_price": float(order.trigger_price or 0.0),
            "is_amo": False,
        }

    def _parse_order_response(
        self,
        fallback_order_id: str,
        request: OrderRequest,
        response: Any,
    ) -> BrokerOrder:
        """Convert a live SDK response into a BrokerOrder snapshot."""
        order_id = (
            _safe_get(response, "order_id")
            or _safe_get(response, "id")
            or fallback_order_id
        )
        status = _status_from_value(
            _safe_get(response, "status") or _safe_get(response, "order_status")
        )
        if status == OrderStatus.PENDING and request.order_type == "MARKET":
            # SDKs often acknowledge market orders as pending even though the
            # exchange may fill them very quickly. Keep the raw response.
            status = OrderStatus.PENDING

        return BrokerOrder(
            order_id=str(order_id),
            request=request,
            status=status,
            filled_quantity=int(_safe_get(response, "filled_quantity", 0) or 0),
            average_fill_price=_safe_get(response, "average_price")
            or _safe_get(response, "avg_price")
            or _safe_get(response, "fill_price"),
            rejection_reason=str(
                _safe_get(response, "rejection_reason")
                or _safe_get(response, "message")
                or ""
            ),
            raw=self._serialize_raw(response),
        )

    def _reject_order(
        self,
        request: OrderRequest,
        reason: str,
        order_id: Optional[str] = None,
    ) -> BrokerOrder:
        """Store a rejected order snapshot locally."""
        rejected = BrokerOrder(
            order_id=order_id or request.client_order_id or str(uuid.uuid4())[:16],
            request=request,
            status=OrderStatus.REJECTED,
            rejection_reason=reason,
            raw={"reason": reason},
        )
        self._orders.append(rejected)
        logger.warning(
            "Order rejected: %s %s x%s (%s)",
            request.side,
            request.symbol,
            request.quantity,
            reason,
        )
        return rejected

    @staticmethod
    def _serialize_raw(response: Any) -> Dict[str, Any]:
        """Best-effort JSON-friendly response snapshot."""
        if response is None:
            return {}
        if isinstance(response, dict):
            return dict(response)
        raw: Dict[str, Any] = {}
        for key in dir(response):
            if key.startswith("_"):
                continue
            try:
                value = getattr(response, key)
            except Exception:
                continue
            if callable(value):
                continue
            try:
                raw[key] = value
            except Exception:
                continue
        return raw

    @staticmethod
    def _call_first(api: Any, method_names: Sequence[str], *args: Any, **kwargs: Any) -> Any:
        """
        Call the first available method on an SDK object.

        This keeps the implementation compatible with small SDK surface
        differences across Upstox client versions.
        """
        for name in method_names:
            method = getattr(api, name, None)
            if method is None:
                continue
            return method(*args, **kwargs)
        raise BrokerError(
            f"None of the methods {tuple(method_names)} exist on {type(api).__name__}"
        )

    @staticmethod
    def _invoke_with_payload(api: Any, method_names: Sequence[str], payload: Any) -> Any:
        """
        Call the first available method, trying positional and common keyword
        argument names.
        """
        last_error: Optional[Exception] = None
        for name in method_names:
            method = getattr(api, name, None)
            if method is None:
                continue
            for call in (
                lambda: method(payload),
                lambda: method(body=payload),
                lambda: method(request=payload),
            ):
                try:
                    return call()
                except TypeError as exc:
                    last_error = exc
                    continue
                except Exception:
                    raise
        if last_error is not None:
            raise last_error
        raise BrokerError(
            f"None of the methods {tuple(method_names)} exist on {type(api).__name__}"
        )

    def _fetch_remote_positions(self) -> Optional[List[BrokerPosition]]:
        """Try to read positions from the live SDK."""
        if not self._connected or self._portfolio_api is None:
            return None

        try:
            payload = self._call_first(
                self._portfolio_api,
                ("get_positions", "get_net_positions", "get_holdings"),
            )
        except Exception as exc:
            logger.debug("Remote positions fetch failed: %s", exc)
            return None

        items = self._extract_collection(payload)
        if not items:
            return []

        parsed: List[BrokerPosition] = []
        for item in items:
            symbol = (
                _safe_get(item, "tradingsymbol")
                or _safe_get(item, "trading_symbol")
                or _safe_get(item, "symbol")
                or _safe_get(item, "instrument_key")
                or ""
            )
            qty = int(_safe_get(item, "quantity", _safe_get(item, "qty", 0)) or 0)
            avg = float(
                _safe_get(item, "average_price")
                or _safe_get(item, "avg_price")
                or _safe_get(item, "buy_price")
                or 0.0
            )
            direction = int(_safe_get(item, "direction", 1) or 1)
            if qty <= 0 or avg <= 0 or not symbol:
                continue
            parsed.append(
                BrokerPosition(
                    symbol=str(symbol),
                    quantity=qty,
                    average_price=avg,
                    direction=1 if direction >= 0 else -1,
                    instrument_key=str(_safe_get(item, "instrument_key", "")),
                    product=str(_safe_get(item, "product", self.product)),
                    realized_pnl=float(_safe_get(item, "realized_pnl", 0.0) or 0.0),
                    unrealized_pnl=float(_safe_get(item, "unrealized_pnl", 0.0) or 0.0),
                    market_price=_safe_get(item, "ltp") or _safe_get(item, "last_price"),
                    opened_at=_utc_now(),
                    updated_at=_utc_now(),
                    metadata=self._serialize_raw(item),
                )
            )
        return parsed

    def _fetch_remote_balance(self) -> Optional[AccountBalance]:
        """Try to read available funds from the live SDK."""
        if not self._connected:
            return None

        if self._funds_api is None and self._portfolio_api is None:
            return None

        api_candidates = [api for api in (self._funds_api, self._portfolio_api) if api is not None]
        method_candidates = (
            "get_funds",
            "get_balance",
            "get_account_balance",
            "get_user_fund_margin",
            "fund_margin",
            "get_margin",
        )

        for api in api_candidates:
            try:
                payload = self._call_first(api, method_candidates)
            except Exception:
                continue

            data = self._first_payload(payload)
            if data is None:
                continue

            cash = float(
                _safe_get(data, "available_cash")
                or _safe_get(data, "available_margin")
                or _safe_get(data, "cash")
                or _safe_get(data, "balance")
                or self._balance.cash
            )
            equity = float(
                _safe_get(data, "equity")
                or _safe_get(data, "net_worth")
                or cash + float(_safe_get(data, "unrealized_pnl", 0.0) or 0.0)
            )
            margin_used = float(_safe_get(data, "margin_used", 0.0) or 0.0)
            unrealized = float(_safe_get(data, "unrealized_pnl", 0.0) or 0.0)
            realized = float(_safe_get(data, "realized_pnl", 0.0) or 0.0)
            currency = str(_safe_get(data, "currency", "INR") or "INR")

            return AccountBalance(
                cash=cash,
                available_cash=cash,
                equity=equity,
                margin_used=margin_used,
                unrealized_pnl=unrealized,
                realized_pnl=realized,
                currency=currency,
                updated_at=_utc_now(),
                metadata=self._serialize_raw(data),
            )

        return None

    def _fetch_remote_orders(self) -> Optional[List[BrokerOrder]]:
        """Try to read order history from the live SDK."""
        if not self._connected or self._order_api is None:
            return None

        try:
            payload = self._call_first(
                self._order_api,
                ("get_orders", "get_order_book", "orders"),
            )
        except Exception as exc:
            logger.debug("Remote orders fetch failed: %s", exc)
            return None

        items = self._extract_collection(payload)
        if not items:
            return []

        parsed: List[BrokerOrder] = []
        for item in items:
            request = OrderRequest(
                symbol=str(
                    _safe_get(item, "tradingsymbol")
                    or _safe_get(item, "trading_symbol")
                    or _safe_get(item, "symbol")
                    or ""
                ),
                side=str(_safe_get(item, "transaction_type", "BUY")),
                quantity=int(_safe_get(item, "quantity", 0) or 0) or 1,
                instrument_key=str(_safe_get(item, "instrument_key", "")),
                order_type=str(_safe_get(item, "order_type", "MARKET")),
                product=str(_safe_get(item, "product", self.product)),
                price=_safe_get(item, "price"),
                trigger_price=_safe_get(item, "trigger_price"),
                validity=str(_safe_get(item, "validity", "DAY")),
                tag=str(_safe_get(item, "tag", "")),
                client_order_id=str(_safe_get(item, "client_order_id", "")),
                metadata=self._serialize_raw(item),
            )
            parsed.append(
                BrokerOrder(
                    order_id=str(_safe_get(item, "order_id", uuid.uuid4().hex[:16])),
                    request=request,
                    status=_status_from_value(_safe_get(item, "status")),
                    filled_quantity=int(_safe_get(item, "filled_quantity", 0) or 0),
                    average_fill_price=_safe_get(item, "average_price")
                    or _safe_get(item, "avg_price")
                    or _safe_get(item, "fill_price"),
                    rejection_reason=str(_safe_get(item, "rejection_reason", "") or ""),
                    raw=self._serialize_raw(item),
                )
            )
        return parsed

    @staticmethod
    def _extract_collection(payload: Any) -> List[Any]:
        """Normalise common SDK response shapes into a list of items."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "items", "orders", "positions", "holdings", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    return list(value.values())
            return [payload]

        # Objects returned by the SDK often expose a .data field.
        data = _safe_get(payload, "data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "orders", "positions", "holdings", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return [data]
        if data is not None:
            return [data]

        # Some SDK responses are direct collections exposed via iterable attrs.
        return []

    @staticmethod
    def _first_payload(payload: Any) -> Any:
        """Extract the most useful single object from a payload."""
        if payload is None:
            return None
        if isinstance(payload, dict):
            for key in ("data", "result", "funds", "balance", "account"):
                if key in payload and payload[key] is not None:
                    return payload[key]
            return payload
        data = _safe_get(payload, "data")
        return data if data is not None else payload


__all__ = ["UpstoxBroker"]
