"""
backtester/commission.py
------------------------
Broker-agnostic commission layer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class Segment(Enum):
    EQUITY_DELIVERY   = "equity_delivery"
    EQUITY_INTRADAY   = "equity_intraday"
    EQUITY_FUTURES    = "equity_futures"
    EQUITY_OPTIONS    = "equity_options"
    CURRENCY_FUTURES  = "currency_futures"
    CURRENCY_OPTIONS  = "currency_options"
    COMMODITY_FUTURES = "commodity_futures"
    COMMODITY_OPTIONS = "commodity_options"

@dataclass(slots=True)
class ChargeBreakdown:
    segment: str = ""
    side: str = ""
    quantity: int = 0
    price: float = 0.0
    trade_value: float = 0.0
    brokerage: float = 0.0
    stt: float = 0.0
    transaction_charge: float = 0.0
    sebi_fee: float = 0.0
    gst: float = 0.0
    stamp_duty: float = 0.0
    dp_charge: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict:
        return {
            "segment": self.segment,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "trade_value": self.trade_value,
            "brokerage": self.brokerage,
            "stt": self.stt,
            "transaction_charge": self.transaction_charge,
            "sebi_fee": self.sebi_fee,
            "gst": self.gst,
            "stamp_duty": self.stamp_duty,
            "dp_charge": self.dp_charge,
            "total": self.total,
        }

class CommissionBase(ABC):
    @abstractmethod
    def calculate(
        self,
        side: str,
        quantity: int,
        price: float,
        segment: str,
    ) -> ChargeBreakdown:
        pass

    @abstractmethod
    def segment_names(self) -> list[str]:
        pass

class IndianEquityCommission(CommissionBase):
    """Full 7-layer Indian market charge model (default)."""
    BROKERAGE_CAP = 20.0
    BROKERAGE_PCT = {
        Segment.EQUITY_DELIVERY: 0.001, Segment.EQUITY_INTRADAY: 0.0005,
        Segment.EQUITY_FUTURES: 0.0005, Segment.EQUITY_OPTIONS: None,
        Segment.CURRENCY_FUTURES: 0.0005, Segment.CURRENCY_OPTIONS: None,
        Segment.COMMODITY_FUTURES: 0.0005, Segment.COMMODITY_OPTIONS: None,
    }
    STT_RATES = {
        Segment.EQUITY_DELIVERY: (0.001, 0.001),
        Segment.EQUITY_INTRADAY: (0.00025, 0.00025),
        Segment.EQUITY_FUTURES: (0.0, 0.0001250),
        Segment.EQUITY_OPTIONS: (0.000625, 0.00125),
        Segment.CURRENCY_FUTURES: (0.0, 0.0),
        Segment.CURRENCY_OPTIONS: (0.0, 0.0),
        Segment.COMMODITY_FUTURES: (0.0, 0.0001),
        Segment.COMMODITY_OPTIONS: (0.0, 0.0001),
    }
    TRANSACTION_RATES = {
        Segment.EQUITY_DELIVERY: 0.0000297, Segment.EQUITY_INTRADAY: 0.0000297,
        Segment.EQUITY_FUTURES: 0.0000173, Segment.EQUITY_OPTIONS: 0.0003503,
        Segment.CURRENCY_FUTURES: 0.0000035, Segment.CURRENCY_OPTIONS: 0.0003503,
        Segment.COMMODITY_FUTURES: 0.000026, Segment.COMMODITY_OPTIONS: 0.000026,
    }
    SEBI_RATE = 0.0000001
    GST_RATE = 0.18
    STAMP_DUTY_RATES = {
        Segment.EQUITY_DELIVERY: 0.00015, Segment.EQUITY_INTRADAY: 0.000003,
        Segment.EQUITY_FUTURES: 0.000002, Segment.EQUITY_OPTIONS: 0.000003,
        Segment.CURRENCY_FUTURES: 0.000001, Segment.CURRENCY_OPTIONS: 0.000001,
        Segment.COMMODITY_FUTURES: 0.000001, Segment.COMMODITY_OPTIONS: 0.000001,
    }
    DP_CHARGE_PER_SCRIP = 18.5

    def calculate(self, side: str, quantity: int, price: float, segment: str) -> ChargeBreakdown:
        side = side.upper().strip()
        if side not in ("BUY", "SELL"): raise ValueError(f"side must be BUY/SELL, got: {side}")
        if quantity <= 0: raise ValueError(f"quantity must be > 0, got: {quantity}")
        if price <= 0.0: raise ValueError(f"price must be > 0.0, got: {price}")
        
        try:
            seg_enum = Segment(segment)
        except ValueError:
            raise ValueError(f"Unknown segment: {segment}")
            
        tv = quantity * price
        r = ChargeBreakdown(segment=segment, side=side, quantity=quantity,
                            price=price, trade_value=tv)
        r.brokerage = min(self.BROKERAGE_CAP, (self.BROKERAGE_PCT[seg_enum] or 0) * tv) \
                      if self.BROKERAGE_PCT[seg_enum] else self.BROKERAGE_CAP
        buy_rate, sell_rate = self.STT_RATES[seg_enum]
        r.stt = tv * (buy_rate if side == "BUY" else sell_rate)
        r.transaction_charge = tv * self.TRANSACTION_RATES[seg_enum]
        r.sebi_fee = tv * self.SEBI_RATE
        r.gst = (r.brokerage + r.transaction_charge) * self.GST_RATE
        r.stamp_duty = tv * self.STAMP_DUTY_RATES[seg_enum] if side == "BUY" else 0.0
        r.dp_charge = self.DP_CHARGE_PER_SCRIP if (seg_enum == Segment.EQUITY_DELIVERY and side == "SELL") else 0.0
        r.total = round(r.brokerage + r.stt + r.transaction_charge +
                        r.sebi_fee + r.gst + r.stamp_duty + r.dp_charge, 2)
        for attr in ("brokerage","stt","transaction_charge","sebi_fee","gst","stamp_duty","dp_charge"):
            setattr(r, attr, round(getattr(r, attr), 2))
        return r

    def segment_names(self) -> list[str]:
        return [s.value for s in Segment]

class ZeroCommission(CommissionBase):
    """Returns 0 for all charges. Useful for clean P&L testing."""
    def calculate(self, side: str, quantity: int, price: float, segment: str) -> ChargeBreakdown:
        side = side.upper().strip()
        if side not in ("BUY", "SELL"): raise ValueError(f"side must be BUY/SELL, got: {side}")
        if quantity <= 0: raise ValueError(f"quantity must be > 0, got: {quantity}")
        if price <= 0.0: raise ValueError(f"price must be > 0.0, got: {price}")
        
        return ChargeBreakdown(
            segment=segment, side=side, quantity=quantity,
            price=price, trade_value=quantity * price
        )

    def segment_names(self) -> list[str]:
        return [s.value for s in Segment]

class FixedCommission(CommissionBase):
    """Fixed amount per side, no percentage."""
    def __init__(self, per_trade: float = 20.0):
        self.per_trade = per_trade

    def calculate(self, side: str, quantity: int, price: float, segment: str) -> ChargeBreakdown:
        side = side.upper().strip()
        if side not in ("BUY", "SELL"): raise ValueError(f"side must be BUY/SELL, got: {side}")
        if quantity <= 0: raise ValueError(f"quantity must be > 0, got: {quantity}")
        if price <= 0.0: raise ValueError(f"price must be > 0.0, got: {price}")
        
        r = ChargeBreakdown(
            segment=segment, side=side, quantity=quantity,
            price=price, trade_value=quantity * price
        )
        r.brokerage = self.per_trade
        r.total = round(self.per_trade, 2)
        return r

    def segment_names(self) -> list[str]:
        return [s.value for s in Segment]

def infer_segment(instrument_type: str, holding_type: str = "CNC") -> str:
    """Maps instrument type + holding type to segment string."""
    it = instrument_type.upper()
    ht = holding_type.upper()
    if it == "EQUITY":
        return Segment.EQUITY_INTRADAY.value if ht == "MIS" else Segment.EQUITY_DELIVERY.value
    if it in ("FUTSTK", "FUTIDX"): return Segment.EQUITY_FUTURES.value
    if it in ("OPTSTK", "OPTIDX"): return Segment.EQUITY_OPTIONS.value
    if it in ("FUTCUR",): return Segment.CURRENCY_FUTURES.value
    if it in ("OPTCUR",): return Segment.CURRENCY_OPTIONS.value
    if it in ("FUTCOM",): return Segment.COMMODITY_FUTURES.value
    if it in ("OPTCOM",): return Segment.COMMODITY_OPTIONS.value
    raise ValueError(f"Unknown instrument_type={instrument_type!r}, holding_type={holding_type!r}")

def commission_from_broker(broker_name: str) -> CommissionBase:
    import importlib
    try:
        module = importlib.import_module(f"broker.{broker_name}.commission")
        class_name = broker_name.capitalize() + "Commission"
        cls = getattr(module, class_name)
        return cls()
    except ImportError as e:
        raise ImportError(f"Could not load commission model for broker '{broker_name}': {e}")
    except AttributeError:
        # e.g. class UpstoxCommission not found in broker.upstox.commission
        raise ImportError(f"Broker commission module found, but it does not define '{broker_name.capitalize()}Commission'.")
