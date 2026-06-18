from abc import ABC, abstractmethod
from live_bot.models import TickData, PortfolioUpdate, FeedMode

class FeedAdapterBase(ABC):
    """
    Broker-agnostic feed contract.
    Concrete adapters implement broker-specific parsing.
    """
    @abstractmethod
    def parse_market_message(
        self,
        raw_message: dict,
        instrument_map: dict[str, str],
    ) -> list[TickData]:
        """Parse real-time market data message into standard TickData."""
        pass

    @abstractmethod
    def parse_portfolio_message(
        self,
        raw_message: dict,
    ) -> PortfolioUpdate | None:
        """Parse portfolio update (orders/positions/holdings) into standard update."""
        pass

    @abstractmethod
    def parse_rest_quote(
        self,
        raw_response: dict,
        instrument_map: dict[str, str],
    ) -> list[TickData]:
        """Parse REST API quote/LTP response into standard TickData."""
        pass

    @abstractmethod
    def get_websocket_subscribe_payload(
        self,
        instrument_keys: list[str],
        mode: FeedMode,
    ) -> dict:
        """Generate broker-specific websocket subscribe payload."""
        pass
