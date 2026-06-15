"""
screener/rules/strategy.py
--------------------------
Rules that integrate backtesting strategies into the screener.
"""

from typing import Any, Type

import pandas as pd

from screener.base import RuleResult
from screener.rules.base import ScreenRule


class StrategyRule(ScreenRule):
    """
    Evaluates a specific trading strategy on the latest data.
    """
    def __init__(self, strategy_class: Type[Any], strategy_params: dict, signal_type: str = "long"):
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.signal_type = signal_type.lower()
        
        self.name = f"StrategyRule_{self.strategy_class.__name__}_{self.signal_type}"
        self.description = f"Checks if {self.strategy_class.__name__} generated a {self.signal_type} signal."
        
    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        strategy = self.strategy_class(**self.strategy_params)
        signals_df = strategy.generate_signals(df)
        
        if signals_df is None or signals_df.empty or "signal" not in signals_df.columns:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                value=None,
                threshold=None,
                details={"error": "no signal column"},
                weight=self.weight
            )
            
        latest_signal = signals_df["signal"].iloc[-1]
        
        target_signal = 1 if self.signal_type == "long" else -1
        
        passed = (latest_signal == target_signal)
        
        return RuleResult(
            rule_name=self.name,
            passed=bool(passed),
            value=float(latest_signal) if not pd.isna(latest_signal) else None,
            threshold=target_signal,
            details={"signal_type": self.signal_type},
            weight=self.weight
        )


class StrategyConfluenceRule(ScreenRule):
    """
    Evaluates multiple StrategyRules and passes if at least n_required pass.
    """
    def __init__(self, strategies: list[StrategyRule], n_required: int):
        self.strategies = strategies
        self.n_required = n_required
        
        self.name = f"StrategyConfluence_{self.n_required}_{len(strategies)}"
        self.description = f"Requires {self.n_required} out of {len(strategies)} strategies to pass."

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        passed_count = 0
        details = {}
        
        for strat in self.strategies:
            res = strat.evaluate_safe(df)
            details[strat.name] = res.passed
            if res.passed:
                passed_count += 1
                
        passed = passed_count >= self.n_required
        score = passed_count / len(self.strategies) if self.strategies else 0.0
        
        details["passed_count"] = passed_count
        details["total_strategies"] = len(self.strategies)
        details["n_required"] = self.n_required
        
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            value=score,
            threshold=float(self.n_required) / len(self.strategies) if self.strategies else 0.0,
            details=details,
            weight=self.weight
        )
