import logging
from typing import Optional, Dict, List
from live_bot.models import LiveOrder, LivePosition
from live_bot.state import LiveState
from live_bot.orders.base import BrokerInterface

logger = logging.getLogger(__name__)

class OrderManager:
    """
    Unified order lifecycle manager.
    Delegates to broker (paper or live).
    Maintains order book and trade history.
    """
    def __init__(self, broker: BrokerInterface, state: LiveState, risk_guard=None, session_store=None):
        self.broker = broker
        self.state = state
        self.risk_guard = risk_guard
        self.session_store = session_store

    def place_order(self, symbol: str, instrument_key: str, action: str, quantity: int,
                    order_type: str = "MARKET", limit_price: Optional[float] = None,
                    stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
                    strategy_tag: str = "") -> Optional[LiveOrder]:
        
        if self.risk_guard and not self.risk_guard.allow_order(symbol, action, quantity, self.state.total_value):
            logger.warning(f"Order for {symbol} rejected by RiskGuard.")
            return None
            
        order = self.broker.place_order(
            symbol, instrument_key, action, quantity, order_type,
            limit_price, stop_loss, take_profit, strategy_tag
        )
        
        if order and self.session_store:
            self.session_store.save_order(order)
            
        return order

    def cancel_order(self, order_id: str) -> bool:
        # Assuming broker has cancel_order
        if hasattr(self.broker, "cancel_order"):
            return self.broker.cancel_order(order_id)
        return False

    def get_order_book(self) -> List[LiveOrder]:
        return list(self.state.get_all_orders().values())

    def get_positions(self) -> Dict[str, LivePosition]:
        return self.state.get_all_positions()

    def sync_positions_from_broker(self):
        if hasattr(self.broker, "sync_positions"):
            self.broker.sync_positions()

    def squareoff_all(self, reason: str):
        logger.info(f"Squaring off all positions. Reason: {reason}")
        self.broker.squareoff_all()
        if self.session_store:
            # log squareoff event
            pass
