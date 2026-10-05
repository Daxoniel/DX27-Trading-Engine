from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSnapshot:
    """Completed-bar features available to the intraday strategy.

    ``None`` values deliberately describe insufficient history rather than
    manufacturing an indicator value from future bars.
    """

    opening_range_high: float | None
    opening_range_low: float | None
    opening_range_ready: bool
    atr: float | None
    adx: float | None
    indicators_ready: bool
