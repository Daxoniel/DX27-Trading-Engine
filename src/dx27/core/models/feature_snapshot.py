from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSnapshot:
    previous_high_20: float
    average_volume_20: float
    atr_14: float