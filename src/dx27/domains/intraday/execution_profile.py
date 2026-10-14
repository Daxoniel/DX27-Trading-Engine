"""Fixed engineering scenarios; these parameters do not tune the ORB bot."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class HistoricalExecutionProfile:
    entry_delay_minutes: int = 0
    exit_delay_minutes: int = 0
    fill_fraction: float = 1.0
    entry_reservation_buffer_bps: float = 0.0
    reject_every_nth_entry: int = 0
    uncertain_every_nth_entry: int = 0
    uncertainty_mode: str = "accepted"
    reconciliation_delay_minutes: int = 2
    lose_cancel_replies: bool = False
    duplicate_reports: bool = True

    def __post_init__(self):
        for name in ("entry_delay_minutes", "exit_delay_minutes", "reject_every_nth_entry", "uncertain_every_nth_entry", "reconciliation_delay_minutes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
                raise ValueError(name + " requires a bounded nonnegative integer")
        if isinstance(self.fill_fraction, bool) or not isfinite(self.fill_fraction) or not 0 < self.fill_fraction <= 1:
            raise ValueError("fill_fraction must be in (0, 1]")
        if isinstance(self.entry_reservation_buffer_bps, bool) or not isfinite(self.entry_reservation_buffer_bps) or not 0 <= self.entry_reservation_buffer_bps <= 1000:
            raise ValueError("reservation buffer must be between 0 and 1000 bps")
        if self.uncertainty_mode not in {"accepted", "not_found"}:
            raise ValueError("uncertainty_mode must be accepted or not_found")
        if not isinstance(self.lose_cancel_replies, bool) or not isinstance(self.duplicate_reports, bool):
            raise ValueError("scenario switches must be booleans")
