"""
backtester/config.py
--------------------
Backtest configuration dataclass and SegmentPreset factory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import time as dtime
from enum import Enum

from backtester.orders import OrderType, StopLossType, TakeProfitType
from backtester.commission import CommissionBase, IndianEquityCommission, Segment
from risk.config import RiskConfig

logger = logging.getLogger(__name__)

INTRADAY_SQUAREOFF = dtime(15, 20)

class TrailingType(Enum):
    """Whether trailing stop distance is measured in % or fixed ₹ amount."""
    PERCENT = "PERCENT"
    AMOUNT  = "AMOUNT"

class SegmentPreset:
    """
    Factory for common BacktestConfig setups.
    """

    @staticmethod
    def intraday(
        capital:        float = 500_000.0,
        allow_shorting: bool  = True,
        **kwargs,
    ) -> "BacktestConfig":
        return BacktestConfig(
            initial_capital    = capital,
            segment            = Segment.EQUITY_INTRADAY,
            allow_shorting     = allow_shorting,
            intraday_squareoff = True,
            **kwargs,
        )

    @staticmethod
    def delivery(
        capital:        float = 500_000.0,
        allow_shorting: bool  = False,
        **kwargs,
    ) -> "BacktestConfig":
        return BacktestConfig(
            initial_capital    = capital,
            segment            = Segment.EQUITY_DELIVERY,
            allow_shorting     = allow_shorting,
            intraday_squareoff = False,
            **kwargs,
        )

    @staticmethod
    def futures(
        capital:        float = 500_000.0,
        allow_shorting: bool  = True,
        **kwargs,
    ) -> "BacktestConfig":
        return BacktestConfig(
            initial_capital    = capital,
            segment            = Segment.EQUITY_FUTURES,
            allow_shorting     = allow_shorting,
            intraday_squareoff = False,
            **kwargs,
        )

    @staticmethod
    def options_buy(
        capital:        float = 200_000.0,
        **kwargs,
    ) -> "BacktestConfig":
        return BacktestConfig(
            initial_capital    = capital,
            segment            = Segment.EQUITY_OPTIONS,
            allow_shorting     = False,
            intraday_squareoff = False,
            **kwargs,
        )

    @staticmethod
    def from_string(
        preset:  str,
        capital: float = 500_000.0,
        **kwargs,
    ) -> "BacktestConfig":
        _map = {
            "intraday":    SegmentPreset.intraday,
            "mis":         SegmentPreset.intraday,
            "delivery":    SegmentPreset.delivery,
            "cnc":         SegmentPreset.delivery,
            "swing":       SegmentPreset.delivery,
            "futures":     SegmentPreset.futures,
            "nrml":        SegmentPreset.futures,
            "options_buy": SegmentPreset.options_buy,
            "options":     SegmentPreset.options_buy,
        }
        key = preset.lower().strip()
        if key not in _map:
            raise ValueError(
                f"Unknown segment preset: {preset!r}. "
                f"Valid values: {sorted(_map.keys())}"
            )
        return _map[key](capital=capital, **kwargs)


@dataclass
class BacktestConfig:
    """
    Complete configuration for one backtest run.
    """
    # ── Capital & sizing ────────────────────────────────────────────────────
    initial_capital:    float           = 500_000.0
    capital_risk_pct:   float           = 0.02
    fixed_quantity:     int             = 0
    max_positions:      int             = 0
    max_drawdown_pct:   float           = 0.20
    portfolio_mode:     bool            = False
    pyramid_max:        int             = 1
    # ── Market parameters ───────────────────────────────────────────────────
    segment:            Segment         = Segment.EQUITY_DELIVERY
    allow_shorting:     bool            = False
    intraday_squareoff: bool            = False
    lot_size:           int             = 1
    slippage_pct:       float           = 0.0
    # ── Stop / size helpers ─────────────────────────────────────────────────
    stop_loss_atr_mult: float           = 2.0
    # ── Order type settings ─────────────────────────────────────────────────
    default_order_type:   OrderType      = OrderType.MARKET
    limit_offset_pct:     float          = 0.2
    stop_loss_pct:        float          = 0.0
    use_trailing_stop:    bool           = False
    trailing_stop_pct:    float          = 0.0
    trailing_stop_amt:    float          = 0.0
    default_stop_type:    StopLossType   = StopLossType.NONE
    default_target_type:  TakeProfitType = TakeProfitType.NONE
    default_stop_value:   float          = 0.0
    default_target_value: float          = 0.0
    default_target_rr:    float          = 0.0
    amo_orders:           bool           = False
    gtt_expiry_bars:      int            = 0
    # ── Risk config ─────────────────────────────────────────────────────────
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    # ── Output flags ────────────────────────────────────────────────────────
    save_trade_log:      bool           = False
    save_raw_data:       bool           = False
    save_chart:          bool           = False
    generate_summary:    bool           = False
    run_label:           str            = "backtest"
    max_candles:         int            = 2000
    # ── Commission ──────────────────────────────────────────────────────────
    commission:         CommissionBase  = field(default_factory=IndianEquityCommission)

    def validate(self) -> None:
        """Raise ValueError for obviously wrong configurations."""
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if not (0.0 < self.capital_risk_pct <= 1.0):
            raise ValueError("capital_risk_pct must be in (0, 1]")
        if self.fixed_quantity < 0:
            raise ValueError("fixed_quantity must be >= 0")
        if self.max_drawdown_pct <= 0 or self.max_drawdown_pct > 1:
            raise ValueError("max_drawdown_pct must be in (0, 1]")
        if self.use_trailing_stop:
            if self.trailing_stop_pct == 0 and self.trailing_stop_amt == 0:
                raise ValueError(
                    "use_trailing_stop=True requires trailing_stop_pct or trailing_stop_amt > 0"
                )
            if self.trailing_stop_pct > 0 and self.trailing_stop_amt > 0:
                raise ValueError(
                    "Provide trailing_stop_pct OR trailing_stop_amt, not both"
                )
        if not isinstance(self.commission, CommissionBase):
            raise ValueError("commission must be an instance of CommissionBase")
        if self.pyramid_max < 1:
            raise ValueError("pyramid_max must be >= 1")
        if self.slippage_pct < 0.0:
            raise ValueError("slippage_pct must be >= 0.0")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be > 0")

    def __post_init__(self):
        self.validate()
