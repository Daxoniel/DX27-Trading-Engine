from dataclasses import dataclass


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    triggered: bool
    score: float = 0.0
    reason: str = ""