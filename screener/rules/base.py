"""
screener/rules/base.py
----------------------
Abstract Base Class for all screening rules.
"""

import logging
from abc import ABC, abstractmethod

import pandas as pd

from screener.base import RuleResult

logger = logging.getLogger(__name__)


class ScreenRule(ABC):
    """
    Abstract Base Class for a screener rule.
    """
    name: str = "BaseRule"
    description: str = "Base rule"
    min_bars_required: int = 1
    weight: float = 1.0

    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> RuleResult:
        """
        Evaluate the rule against an OHLCV DataFrame.
        This method must be implemented by subclasses.
        """
        ...

    def evaluate_safe(self, df: pd.DataFrame) -> RuleResult:
        """
        Wraps evaluate() in try/except and enforces min_bars_required.
        Returns a failed RuleResult on error or insufficient data.
        """
        if len(df) < self.min_bars_required:
            logger.debug(f"Rule {self.name} failed: insufficient bars (needs {self.min_bars_required}, got {len(df)})")
            return RuleResult(
                rule_name=self.name,
                passed=False,
                value=None,
                threshold=None,
                details={"error": "insufficient_data"},
                weight=self.weight
            )
        try:
            return self.evaluate(df)
        except Exception as e:
            logger.exception(f"Rule {self.name} evaluation error: {e}")
            return RuleResult(
                rule_name=self.name,
                passed=False,
                value=None,
                threshold=None,
                details={"error": str(e)},
                weight=self.weight
            )

    def to_dict(self) -> dict:
        """
        Serializes rule name + params for JSON storage.
        """
        return {"type": self.__class__.__name__}

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenRule":
        """
        Deserializes from JSON.
        """
        raise NotImplementedError("from_dict must be implemented by serializer or concrete class")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    def __and__(self, other: "ScreenRule") -> "ScreenRule":
        from screener.rules.composite import AndRule
        return AndRule([self, other])

    def __or__(self, other: "ScreenRule") -> "ScreenRule":
        from screener.rules.composite import OrRule
        return OrRule([self, other])

    def __invert__(self) -> "ScreenRule":
        from screener.rules.composite import NotRule
        return NotRule(self)
