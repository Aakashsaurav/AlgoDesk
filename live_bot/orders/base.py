from abc import ABC, abstractmethod
from typing import Optional
from live_bot.models import LiveOrder

class BrokerInterface(ABC):
    @abstractmethod
    def place_order(self, symbol: str, instrument_key: str, action: str, quantity: int,
                    order_type: str, limit_price: Optional[float], stop_loss: Optional[float],
                    take_profit: Optional[float], strategy_tag: str) -> Optional[LiveOrder]: ...

    @abstractmethod
    def check_pending_limit_orders(self, symbol: str) -> None: ...

    @abstractmethod
    def check_stop_loss_take_profit(self, symbol: str) -> None: ...

    @abstractmethod
    def squareoff_all(self) -> None: ...

    @property
    @abstractmethod
    def is_paper(self) -> bool: ...
