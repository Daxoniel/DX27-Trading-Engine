from dataclasses import dataclass


@dataclass(frozen=True)
class LeanInsightSpec:
    symbol: str
    direction: str
    confidence: float
    horizon_days: int