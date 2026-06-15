"""
screener/rules/composite.py
---------------------------
Unlimited nesting logic (AND, OR, NOT, AtLeastN).
"""

from typing import Any

import pandas as pd

from screener.base import RuleResult
from screener.rules.base import ScreenRule


class AndRule(ScreenRule):
    def __init__(self, rules: list[ScreenRule]):
        self.rules = rules
        self.name = "AND(" + ", ".join(r.name for r in rules) + ")"
        self.description = "Logical AND composition"
        self.min_bars_required = max((r.min_bars_required for r in rules), default=1)
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        details = {}
        passed = True
        for rule in self.rules:
            res = rule.evaluate_safe(df)
            details[rule.name] = res
            if not res.passed:
                passed = False
                break  # Short-circuit
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            value=None,
            threshold=None,
            details=details,
            weight=self.weight
        )

    def to_dict(self) -> dict:
        return {
            "type": "AndRule",
            "rules": [r.to_dict() for r in self.rules]
        }

    def __repr__(self) -> str:
        return f"AndRule({self.rules})"


class OrRule(ScreenRule):
    def __init__(self, rules: list[ScreenRule]):
        self.rules = rules
        self.name = "OR(" + ", ".join(r.name for r in rules) + ")"
        self.description = "Logical OR composition"
        self.min_bars_required = max((r.min_bars_required for r in rules), default=1)
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        details = {}
        passed = False
        for rule in self.rules:
            res = rule.evaluate_safe(df)
            details[rule.name] = res
            if res.passed:
                passed = True
                break  # Short-circuit
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            value=None,
            threshold=None,
            details=details,
            weight=self.weight
        )

    def to_dict(self) -> dict:
        return {
            "type": "OrRule",
            "rules": [r.to_dict() for r in self.rules]
        }

    def __repr__(self) -> str:
        return f"OrRule({self.rules})"


class NotRule(ScreenRule):
    def __init__(self, rule: ScreenRule):
        self.rule = rule
        self.name = f"NOT({rule.name})"
        self.description = "Logical NOT composition"
        self.min_bars_required = rule.min_bars_required
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        res = self.rule.evaluate_safe(df)
        return RuleResult(
            rule_name=self.name,
            passed=not res.passed,
            value=None,
            threshold=None,
            details={self.rule.name: res},
            weight=self.weight
        )

    def to_dict(self) -> dict:
        return {
            "type": "NotRule",
            "rule": self.rule.to_dict()
        }

    def __repr__(self) -> str:
        return f"NotRule({self.rule})"


class AtLeastNRule(ScreenRule):
    def __init__(self, rules: list[ScreenRule], n: int):
        self.rules = rules
        self.n = n
        self.name = f"AtLeast{n}(...)"
        self.description = f"At least {n} rules must pass"
        self.min_bars_required = max((r.min_bars_required for r in rules), default=1)
        self.weight = 1.0

    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        details = {}
        passed_count = 0
        for rule in self.rules:
            res = rule.evaluate_safe(df)
            details[rule.name] = res
            if res.passed:
                passed_count += 1
        
        passed = passed_count >= self.n
        score = passed_count / max(1, len(self.rules))
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            value=score,
            threshold=self.n,
            details=details,
            weight=self.weight
        )

    def to_dict(self) -> dict:
        return {
            "type": "AtLeastNRule",
            "n": self.n,
            "rules": [r.to_dict() for r in self.rules]
        }

    def __repr__(self) -> str:
        return f"AtLeastNRule(n={self.n}, rules={self.rules})"
