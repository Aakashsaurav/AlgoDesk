import logging
from typing import Optional, Dict, List
import upstox_client

logger = logging.getLogger(__name__)

class OrderRequest:
    def __init__(self, symbol: str, instrument_token: str, quantity: int, transaction_type: str,
                 order_type: str, price: float = 0.0, trigger_price: float = 0.0,
                 product: str = "I", validity: str = "DAY", tag: str = None):
        self.symbol = symbol
        self.instrument_token = instrument_token
        self.quantity = quantity
        self.transaction_type = transaction_type
        self.order_type = order_type
        self.price = price
        self.trigger_price = trigger_price
        self.product = product
        self.validity = validity
        self.tag = tag

class UpstoxOrderAdapter:
    """
    Upstox-specific order API adapter.
    Translates AlgoDesk's generic OrderRequest to Upstox V3 API calls.
    """
    def __init__(self, access_token: str):
        self.access_token = access_token
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        self.api_client = upstox_client.ApiClient(configuration)
        self.order_api = upstox_client.OrderApi(self.api_client)
        self.portfolio_api = upstox_client.PortfolioApi(self.api_client)
        self.user_api = upstox_client.UserApi(self.api_client)

    def place_order(self, order: OrderRequest) -> dict:
        try:
            req = upstox_client.PlaceOrderV3Request(
                quantity=order.quantity,
                product=order.product,
                validity=order.validity,
                price=order.price,
                tag=order.tag,
                slice=False,
                instrument_token=order.instrument_token,
                order_type=order.order_type,
                transaction_type=order.transaction_type,
                disclosed_quantity=0,
                trigger_price=order.trigger_price,
                is_amo=False,
            )
            response = self.order_api.place_order(req)
            return {"status": "success", "data": getattr(response, "data", {})}
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] place_order failed: {e}")
            return {"status": "error", "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.order_api.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] cancel_order failed for {order_id}: {e}")
            return False

    def modify_order(self, order_id: str, new_qty: int, new_price: float) -> bool:
        try:
            req = upstox_client.ModifyOrderV3Request(
                order_id=order_id,
                quantity=new_qty,
                price=new_price,
            )
            self.order_api.modify_order(req)
            return True
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] modify_order failed for {order_id}: {e}")
            return False

    def get_order_book(self) -> List[dict]:
        try:
            response = self.order_api.get_order_book()
            data = getattr(response, "data", [])
            return [getattr(item, "to_dict", lambda: item)() for item in data]
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] get_order_book failed: {e}")
            return []

    def get_positions(self) -> List[dict]:
        try:
            response = self.portfolio_api.get_positions()
            data = getattr(response, "data", [])
            return [getattr(item, "to_dict", lambda: item)() for item in data]
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] get_positions failed: {e}")
            return []

    def get_holdings(self) -> List[dict]:
        try:
            response = self.portfolio_api.get_holdings()
            data = getattr(response, "data", [])
            return [getattr(item, "to_dict", lambda: item)() for item in data]
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] get_holdings failed: {e}")
            return []

    def get_funds(self) -> dict:
        try:
            response = self.user_api.get_user_fund_margin()
            data = getattr(response, "data", {})
            return getattr(data, "to_dict", lambda: data)() if data else {}
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] get_funds failed: {e}")
            return {}

    def place_gtt_order(self, trigger: float, qty: int, price: float, sl: float) -> Optional[str]:
        try:
            # Stub implementation
            raise NotImplementedError("GTT order placement is not fully implemented in adapter.")
        except Exception as e:
            logger.error(f"[UpstoxOrderAdapter] place_gtt_order failed: {e}")
            return None
