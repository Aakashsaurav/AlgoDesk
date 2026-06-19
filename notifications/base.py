from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from config import IST_TZ

class NotificationPriority(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

@dataclass
class NotificationEvent:
    event_type: str    # "TRADE_ENTRY", "TRADE_EXIT", "RISK_ALERT", etc.
    title: str
    message: str
    priority: NotificationPriority
    symbol: Optional[str] = None
    data: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(IST_TZ))

class NotifierBase(ABC):
    @abstractmethod
    def send(self, event: NotificationEvent) -> bool:
        pass
        
    def send_bulk(self, events: List[NotificationEvent]) -> int:
        success = 0
        for event in events:
            if self.send(event):
                success += 1
        return success
        
    @abstractmethod
    def is_configured(self) -> bool:
        pass
        
    @property
    @abstractmethod
    def name(self) -> str:
        pass
