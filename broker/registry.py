from typing import Type, Dict, List
from broker.base import BrokerBase
from broker.upstox.broker import UpstoxBroker
from config import config

class BrokerRegistry:
    _brokers: Dict[str, Type[BrokerBase]] = {}
    
    @classmethod
    def register(cls, name: str, broker_class: Type[BrokerBase]):
        cls._brokers[name.lower()] = broker_class
        
    @classmethod
    def get(cls, name: str) -> BrokerBase:
        name = name.lower()
        if name not in cls._brokers:
            raise ValueError(f"Broker '{name}' not found. Available: {cls.list_available()}")
        return cls._brokers[name]()
        
    @classmethod
    def get_class(cls, name: str) -> Type[BrokerBase]:
        name = name.lower()
        if name not in cls._brokers:
            raise ValueError(f"Broker '{name}' not found. Available: {cls.list_available()}")
        return cls._brokers[name]
        
    @classmethod
    def list_available(cls) -> List[str]:
        return list(cls._brokers.keys())
        
    @classmethod
    def get_active_broker(cls) -> BrokerBase:
        active = getattr(config, "ACTIVE_BROKER", "upstox")
        return cls.get(active)

# Auto-register Upstox
BrokerRegistry.register("upstox", UpstoxBroker)
