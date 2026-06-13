"""
indicators/support_resistance/models.py
---------------------------------------
Data models for Support and Resistance levels and zones.
"""
from dataclasses import dataclass

@dataclass
class SRLevel:
    """A distinct price level acting as support or resistance."""
    price: float
    strength: float = 1.0  # 0.0 to 1.0
    type: str = "unknown"  # "support", "resistance", "pivot"
    source: str = "unknown" # e.g., "pivot", "swing", "fibonacci"

    def to_dict(self):
        return {
            "price": self.price,
            "strength": self.strength,
            "type": self.type,
            "source": self.source
        }

@dataclass
class SRZone:
    """A price zone acting as support or resistance (e.g. from clustered swings)."""
    lower_price: float
    upper_price: float
    strength: float = 1.0
    type: str = "zone"
    source: str = "unknown"

    def to_dict(self):
        return {
            "lower_price": self.lower_price,
            "upper_price": self.upper_price,
            "strength": self.strength,
            "type": self.type,
            "source": self.source
        }

def sort_by_strength(items):
    """Sort levels or zones by strength descending."""
    return sorted(items, key=lambda x: x.strength, reverse=True)

def filter_near_price(items, price: float, threshold: float = 0.01):
    """Filter levels or zones near a given price within a percentage threshold (0.01 = 1%)."""
    result = []
    for item in items:
        if isinstance(item, SRLevel):
            if abs(item.price - price) / price <= threshold:
                result.append(item)
        elif isinstance(item, SRZone):
            # Distance to nearest edge of the zone
            dist = 0.0
            if price < item.lower_price:
                dist = (item.lower_price - price) / price
            elif price > item.upper_price:
                dist = (price - item.upper_price) / price
            if dist <= threshold:
                result.append(item)
    return result

__all__ = ["SRLevel", "SRZone", "sort_by_strength", "filter_near_price"]
