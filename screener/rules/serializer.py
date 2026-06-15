"""
screener/rules/serializer.py
----------------------------
JSON rule tree serialization logic.
"""

import json
from typing import Any

from screener.rules.base import ScreenRule


class RuleSerializer:
    RULE_REGISTRY: dict[str, type[ScreenRule]] = {}

    @classmethod
    def register_rule(cls, rule_class: type[ScreenRule]):
        cls.RULE_REGISTRY[rule_class.__name__] = rule_class

    @classmethod
    def to_dict(cls, rule: ScreenRule) -> dict:
        """Recursive conversion of ScreenRule tree to dict."""
        return rule.to_dict()

    @classmethod
    def from_dict(cls, data: dict) -> ScreenRule:
        """Recursive reconstruction of ScreenRule tree from dict."""
        if "type" not in data:
            raise ValueError(f"Rule dict must contain 'type' key. Got: {data}")
        
        rule_type = data["type"]
        if rule_type not in cls.RULE_REGISTRY:
            raise ValueError(f"Unknown rule type: {rule_type}")
        
        rule_class = cls.RULE_REGISTRY[rule_type]
        
        # Handle composites specially because they require recursive parsing
        if rule_type in ("AndRule", "OrRule"):
            rules = [cls.from_dict(r) for r in data.get("rules", [])]
            return rule_class(rules)
        elif rule_type == "NotRule":
            rule = cls.from_dict(data["rule"])
            return rule_class(rule)
        elif rule_type == "AtLeastNRule":
            rules = [cls.from_dict(r) for r in data.get("rules", [])]
            n = data.get("n", 1)
            return rule_class(rules, n=n)
        
        return rule_class.from_dict(data)

    @classmethod
    def to_json(cls, rule: ScreenRule) -> str:
        return json.dumps(cls.to_dict(rule), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> ScreenRule:
        data = json.loads(json_str)
        return cls.from_dict(data)

def build_rule_from_dict(data: dict) -> ScreenRule:
    """Convenience function to build rule from dict."""
    return RuleSerializer.from_dict(data)

# Auto-register all known rules at import
from screener.rules.composite import AndRule, OrRule, NotRule, AtLeastNRule
from screener.rules.technical import RSIRule, MACDRule, EMARule, GoldenCrossRule, DeathCrossRule, SupertrendRule, BollingerSqueezeRule, RelativeStrengthRule, ADXRule, VWAPRule
from screener.rules.price import PriceBreakoutRule, NearSupportRule, NearResistanceRule, PriceRangeRule, HigherHighRule, LowerLowRule
from screener.rules.volume import VolumeBreakoutRule, VolumeDeclineRule, VolumeRatioRule, AccumulationRule, DistributionRule
from screener.rules.pattern import CandlePatternRule, ChartPatternRule, TrendStructureRule

for rule_class in [
    AndRule, OrRule, NotRule, AtLeastNRule,
    RSIRule, MACDRule, EMARule, GoldenCrossRule, DeathCrossRule,
    SupertrendRule, BollingerSqueezeRule, RelativeStrengthRule, ADXRule, VWAPRule,
    PriceBreakoutRule, NearSupportRule, NearResistanceRule, PriceRangeRule, HigherHighRule, LowerLowRule,
    VolumeBreakoutRule, VolumeDeclineRule, VolumeRatioRule, AccumulationRule, DistributionRule,
    CandlePatternRule, ChartPatternRule, TrendStructureRule
]:
    RuleSerializer.register_rule(rule_class)
