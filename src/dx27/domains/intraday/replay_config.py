"""Recorded engineering limits for the INTRA-1A long-only baseline."""

from dataclasses import dataclass, field
from datetime import date
from math import isfinite

from dx27.core.models.execution_costs import ExecutionCosts
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


@dataclass(frozen=True)
class IntradayReplayConfig:
    initial_cash: float = 100_000.0
    risk_per_trade: float = 0.0025
    max_open_risk: float = 0.01
    max_position_fraction: float = 0.25
    daily_loss_limit: float = 0.01
    max_positions: int = 3
    max_volume_participation: float = 0.01
    execution_delay_minutes: int = 1
    flatten_minutes_before_close: int = 5
    last_entry_minutes_before_close: int = 10
    adx_threshold: float = 25.0
    atr_period: int = 14
    adx_period: int = 14
    stop_atr: float = 1.0
    target_atr: float = 2.0
    decision_start: date | None = None
    costs: ExecutionCosts = field(default_factory=ExecutionCosts)
    opening_volume: OpeningVolumeConfig | None = None

    def __post_init__(self):
        if self.opening_volume is not None and not isinstance(self.opening_volume, OpeningVolumeConfig):
            raise ValueError("opening_volume must be an OpeningVolumeConfig or None")
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        for name in ("risk_per_trade", "max_open_risk", "max_position_fraction",
                     "daily_loss_limit", "max_volume_participation"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        for name in ("max_positions", "execution_delay_minutes", "flatten_minutes_before_close",
                     "last_entry_minutes_before_close", "atr_period", "adx_period"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.last_entry_minutes_before_close <= self.flatten_minutes_before_close:
            raise ValueError("entry cutoff must precede scheduled flatten")
        for name in ("stop_atr", "target_atr"):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not isfinite(self.adx_threshold) or not 0 <= self.adx_threshold <= 100:
            raise ValueError("adx_threshold must be in [0, 100]")
