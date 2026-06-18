"""
screener/rules/strategy.py
--------------------------
Rules that integrate backtesting strategies into the screener.
"""

from typing import Any, Type, Union

import pandas as pd

from screener.base import RuleResult
from screener.rules.base import ScreenRule


class StrategyRule(ScreenRule):
    """
    Evaluates a specific trading strategy on the latest data.
    """
    def __init__(self, strategy_class: Union[str, Type[Any]], strategy_params: dict, signal_type: str = "long"):
        if isinstance(strategy_class, str):
            from strategies.registry import get_strategy_class
            self.strategy_class = get_strategy_class(strategy_class)
            self.strategy_name = strategy_class
        else:
            self.strategy_class = strategy_class
            self.strategy_name = strategy_class.__name__
            
        self.strategy_params = strategy_params
        self.signal_type = signal_type.lower()
        
        self.name = f"StrategyRule_{self.strategy_name}_{self.signal_type}"
        self.description = f"Checks if {self.strategy_name} generated a {self.signal_type} signal."
        self.min_bars_required = getattr(self.strategy_class, "MIN_WARMUP_BARS", 1)
        
    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        try:
            strategy = self.strategy_class(**self.strategy_params)
            signals_df = strategy.generate_signals(df)
        except Exception as e:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                value=None,
                threshold=None,
                details={"error": f"Strategy validation/execution error: {e}"},
                weight=self.weight
            )
        
        if signals_df is None or signals_df.empty or "signal" not in signals_df.columns:
            return RuleResult(
                rule_name=self.name,
                passed=False,
                value=None,
                threshold=None,
                details={"error": "no signal column or empty dataframe"},
                weight=self.weight
            )
            
        last_row = signals_df.iloc[-1]
        latest_signal = last_row.get("signal", 0)
        
        if pd.isna(latest_signal):
            latest_signal = 0
        else:
            latest_signal = int(latest_signal)
        
        target_signal = 1 if self.signal_type == "long" else -1
        passed = (latest_signal == target_signal)
        
        details = {
            "signal_type": self.signal_type,
            "latest_signal": latest_signal,
        }
        
        if "signal_tag" in signals_df.columns:
            tag = last_row.get("signal_tag", "")
            if not pd.isna(tag):
                details["signal_tag"] = str(tag)
                
        if "confidence" in signals_df.columns:
            conf = last_row.get("confidence")
            if not pd.isna(conf):
                details["confidence"] = float(conf)
                
        if "reason" in signals_df.columns:
            reason = last_row.get("reason", "")
            if not pd.isna(reason):
                details["reason"] = str(reason)
                
        if "order_spec" in signals_df.columns:
            ospec = last_row.get("order_spec")
            if ospec is not None:
                details["order_type"] = ospec.order_type.name
                if getattr(ospec, "tag", None):
                    details["order_tag"] = ospec.tag
        
        # Use confidence as score/value if present
        value = float(details.get("confidence", latest_signal))
        
        return RuleResult(
            rule_name=self.name,
            passed=bool(passed),
            value=value,
            threshold=float(target_signal),
            details=details,
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
        self.min_bars_required = max((r.min_bars_required for r in strategies), default=1)

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        passed_count = 0
        details = {}
        
        for strat in self.strategies:
            res = strat.evaluate_safe(df)
            details[strat.name] = res.passed
            # Also propagate nested details if available
            if res.details:
                details[f"{strat.name}_details"] = res.details
                
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
