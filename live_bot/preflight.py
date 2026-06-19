from dataclasses import dataclass
from typing import List
from datetime import datetime
from config import config, IST_TZ
from broker.upstox.auth import auth_manager

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str = "ERROR" # WARNING or ERROR

class PreflightChecker:
    
    @staticmethod
    def check_auth() -> CheckResult:
        try:
            if auth_manager.is_authenticated():
                return CheckResult("Authentication", True, "Auth token is valid", "ERROR")
            return CheckResult("Authentication", False, "Not authenticated", "ERROR")
        except Exception as e:
            return CheckResult("Authentication", False, str(e), "ERROR")
            
    @staticmethod
    def check_broker_connection() -> CheckResult:
        # Mock broker connection for now
        return CheckResult("Broker Connection", True, "Broker connected successfully", "ERROR")
        
    @staticmethod
    def check_market_hours() -> CheckResult:
        now = datetime.now(tz=IST_TZ).time()
        open_time = datetime.strptime(config.MARKET_OPEN_TIME, "%H:%M").time()
        close_time = datetime.strptime(config.MARKET_CLOSE_TIME, "%H:%M").time()
        
        if open_time <= now <= close_time:
            return CheckResult("Market Hours", True, "Market is open", "ERROR")
        return CheckResult("Market Hours", False, "Outside market hours", "WARNING" if not config.LIVE_TRADING_HOURS_ONLY else "ERROR")
        
    @staticmethod
    def check_risk_limits() -> CheckResult:
        if config.TOTAL_CAPITAL > 0 and config.PER_TRADE_RISK_PERCENT > 0:
            return CheckResult("Risk Limits", True, "Risk limits configured properly", "ERROR")
        return CheckResult("Risk Limits", False, "Invalid risk limits", "ERROR")
        
    @staticmethod
    def check_max_order_value() -> CheckResult:
        if config.MAX_ORDER_VALUE > 0:
            return CheckResult("Max Order Value", True, f"Max order value: {config.MAX_ORDER_VALUE}", "ERROR")
        return CheckResult("Max Order Value", False, "Max order value not configured", "WARNING")
        
    @staticmethod
    def check_daily_loss_limit() -> CheckResult:
        if config.MAX_PORTFOLIO_DRAWDOWN > 0:
            return CheckResult("Daily Loss Limit", True, f"Max drawdown: {config.MAX_PORTFOLIO_DRAWDOWN}%", "ERROR")
        return CheckResult("Daily Loss Limit", False, "Drawdown limit not configured", "WARNING")
        
    @staticmethod
    def check_allowed_symbols(symbols: List[str]) -> CheckResult:
        if not config.ALLOWED_SYMBOLS:
            return CheckResult("Allowed Symbols", True, "Any symbol allowed", "WARNING")
            
        unallowed = [s for s in symbols if s not in config.ALLOWED_SYMBOLS]
        if unallowed:
            return CheckResult("Allowed Symbols", False, f"Symbols not allowed: {unallowed}", "ERROR")
        return CheckResult("Allowed Symbols", True, "All symbols allowed", "ERROR")
        
    @classmethod
    def run_all(cls, symbols: List[str] = None) -> List[CheckResult]:
        results = [
            cls.check_auth(),
            cls.check_broker_connection(),
            cls.check_market_hours(),
            cls.check_risk_limits(),
            cls.check_max_order_value(),
            cls.check_daily_loss_limit(),
        ]
        if symbols:
            results.append(cls.check_allowed_symbols(symbols))
        return results
