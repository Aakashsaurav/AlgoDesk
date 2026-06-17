"""
risk/holiday_calendar.py
-------------------------
NSE Holiday awareness to prevent live bots from firing orders on non-trading days.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Set, List, Dict, Any

logger = logging.getLogger(__name__)

# Fallback basic list of NSE holidays for 2026 (as example)
# The user should override or call load_from_upstox_api()
_DEFAULT_HOLIDAYS = frozenset([
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),   # Mahashivratri
    date(2026, 3, 23),  # Holi
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 9, 15),  # Ganesh Chaturthi
    date(2026, 10, 2),  # Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 8),  # Diwali
    date(2026, 12, 25), # Christmas
])


class NSEHolidayCalendar:
    """
    Manages market holidays and trading days calculations.
    """

    def __init__(self) -> None:
        self.holidays: Set[date] = set(_DEFAULT_HOLIDAYS)

    def is_holiday(self, dt: date) -> bool:
        return dt in self.holidays

    def next_trading_day(self, dt: date) -> date:
        current = dt + timedelta(days=1)
        while current.weekday() > 4 or self.is_holiday(current):
            current += timedelta(days=1)
        return current

    def last_trading_day(self, dt: date) -> date:
        current = dt - timedelta(days=1)
        while current.weekday() > 4 or self.is_holiday(current):
            current -= timedelta(days=1)
        return current

    def is_market_open_today(self, dt: date) -> bool:
        """Returns True if the specified date is a valid trading day."""
        if dt.weekday() > 4:  # 5=Sat, 6=Sun
            return False
        if self.is_holiday(dt):
            return False
        return True

    def load_from_list(self, dates: List[str]) -> None:
        """
        Loads holidays from a list of ISO date strings (e.g. ['2026-01-26']).
        """
        try:
            parsed = [date.fromisoformat(d) for d in dates]
            self.holidays.update(parsed)
            logger.info(f"Loaded {len(parsed)} holidays from list.")
        except Exception as e:
            logger.error(f"Failed to load holidays from list: {e}")

    def load_from_upstox_api(self, api_response: Dict[str, Any]) -> None:
        """
        Parses an Upstox API holiday response into the calendar.
        Expected format typically contains 'data' -> list of dicts with 'date'.
        """
        try:
            # Assuming upstox returns: {'status': 'success', 'data': [{'date': '2026-01-26', ...}, ...]}
            data = api_response.get("data", [])
            new_holidays = []
            for item in data:
                d_str = item.get("date")
                if d_str:
                    new_holidays.append(date.fromisoformat(d_str[:10]))
            
            if new_holidays:
                self.holidays.update(new_holidays)
                logger.info(f"Loaded {len(new_holidays)} holidays from Upstox API.")
        except Exception as e:
            logger.error(f"Failed to load holidays from Upstox API: {e}")

# Global calendar instance for the application to share
calendar = NSEHolidayCalendar()
