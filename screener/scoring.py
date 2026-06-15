from enum import Enum
from typing import Any

from screener.base import RankBy, ScreenResult, RuleResult


class ScoreMode(Enum):
    HIT_COUNT = "HIT_COUNT"
    WEIGHTED = "WEIGHTED"


class Scorer:
    def __init__(self, mode: ScoreMode = ScoreMode.HIT_COUNT):
        self.mode = mode

    def score(self, rule_results: dict[str, RuleResult], weights: dict[str, float] | None = None) -> float:
        if not rule_results:
            return 0.0

        if self.mode == ScoreMode.HIT_COUNT:
            passed = sum(1 for res in rule_results.values() if res.passed)
            return float(passed) / len(rule_results)
        
        elif self.mode == ScoreMode.WEIGHTED:
            total_weight = 0.0
            earned_weight = 0.0
            
            for rule_name, res in rule_results.items():
                w = weights.get(rule_name, res.weight) if weights else res.weight
                total_weight += w
                if res.passed:
                    earned_weight += w
                    
            if total_weight == 0.0:
                return 0.0
                
            return float(earned_weight) / total_weight

        return 0.0

    def rank(self, results: list[ScreenResult], rank_by: RankBy, ascending: bool = False) -> list[ScreenResult]:
        def extract_value(res: ScreenResult, keys: list[str]) -> float | None:
            for key in keys:
                if key in res.indicator_values:
                    return res.indicator_values[key]
            for r in res.rule_details.values():
                if r.details:
                    for key in keys:
                        if key in r.details:
                            return r.details[key]
            return None

        def get_sort_key(res: ScreenResult) -> tuple[int, float]:
            val: float | None = None
            
            if rank_by == RankBy.SCORE:
                val = res.score
            elif rank_by == RankBy.CLOSE:
                val = res.close
            elif rank_by == RankBy.VOLUME:
                val = res.volume
            elif rank_by == RankBy.ATR_PCT:
                val = res.atr_pct
            elif rank_by == RankBy.RS_SCORE:
                val = extract_value(res, ["rs_score", "RS_SCORE"])
                if val is None:
                    val = res.score
            elif rank_by == RankBy.SIGNAL_STRENGTH:
                val = extract_value(res, ["signal_strength", "SIGNAL_STRENGTH"])
                if val is None:
                    val = res.score

            if val is None:
                return (1, 0.0) if ascending else (0, 0.0)
            return (0, float(val)) if ascending else (1, float(val))

        return sorted(results, key=get_sort_key, reverse=not ascending)
