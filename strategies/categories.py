import logging
from enum import Enum

logger = logging.getLogger(__name__)

class StrategyCategory(str, Enum):
    """Stable enumeration for strategy categories used in UI/API filters."""
    MOMENTUM = "Momentum"
    TREND = "Trend"
    MEAN_REVERSION = "Mean Reversion"
    INTRADAY = "Intraday"
    BREAKOUT = "Breakout"
    VOLATILITY = "Volatility"
    STATISTICAL = "Statistical"
    CUSTOM = "Custom"

    @classmethod
    def from_value(cls, value: str) -> "StrategyCategory":
        """
        Return the StrategyCategory matching the given value (case-insensitive).
        Defaults to CUSTOM with a warning if the value is unknown.
        """
        if not value:
            return cls.CUSTOM
            
        value_lower = str(value).strip().lower()
        for member in cls:
            if member.value.lower() == value_lower:
                return member
                
        logger.warning(f"Unknown strategy category: {value!r}. Defaulting to 'Custom'.")
        return cls.CUSTOM
