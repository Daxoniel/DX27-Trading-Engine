"""Immutable transport contracts for Sentinel observations."""

from __future__ import annotations

from dataclasses import dataclass

from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import (
    DataStatus,
    ObservationWindow,
    Provenance,
    SubjectRef,
)
from dx27.intelligence.sentinel.universe import UniverseMembership


def _canonical_provenance(items: tuple[Provenance, ...]) -> tuple[Provenance, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.source_id,
                item.source_record_id or "",
                stable_content_hash(item),
            ),
        )
    )


@dataclass(frozen=True)
class ObservationCoverage:
    """Completeness counts for an observation, independent of market values."""

    expected_observations: int | None = None
    observed_observations: int | None = None

    def __post_init__(self) -> None:
        expected = self.expected_observations
        observed = self.observed_observations
        if (expected is None) != (observed is None):
            raise ValueError("coverage counts must both be provided or both be unknown")
        if expected is None:
            return
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise TypeError("expected_observations must be an integer")
        if not isinstance(observed, int) or isinstance(observed, bool):
            raise TypeError("observed_observations must be an integer")
        if expected <= 0:
            raise ValueError("expected_observations must be positive")
        if observed < 0:
            raise ValueError("observed_observations cannot be negative")
        if observed > expected:
            raise ValueError("observed_observations cannot exceed expected_observations")

    @property
    def coverage_ratio(self) -> float | None:
        if self.expected_observations is None:
            return None
        return self.observed_observations / self.expected_observations


@dataclass(frozen=True)
class ObservationEnvelope:
    """A subject observation and its explicit availability state."""

    subject: SubjectRef
    observation_window: ObservationWindow
    data_status: DataStatus
    provenance: tuple[Provenance, ...]
    universe_membership: UniverseMembership
    market_context: MarketContext | None
    coverage: ObservationCoverage | None = None

    def __post_init__(self) -> None:
        if self.subject.subject_id != self.universe_membership.subject_id:
            raise ValueError("subject and universe membership subject_id must match")
        if not isinstance(self.data_status, DataStatus):
            raise TypeError("data_status must be a DataStatus")
        if not self.provenance:
            raise ValueError("observation provenance must not be empty")
        object.__setattr__(self, "provenance", _canonical_provenance(self.provenance))
        if self.market_context is not None and not isinstance(self.market_context, MarketContext):
            raise TypeError("market_context must be a MarketContext or None")
        if self.data_status is DataStatus.AVAILABLE and self.market_context is None:
            raise ValueError("AVAILABLE observations require market_context")
