"""Immutable event contracts for Sentinel's DETECT stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TypeAlias

from dx27.intelligence.sentinel.identity import (
    ContentIdentity,
    IdentityKind,
    stable_content_hash,
)
from dx27.intelligence.sentinel.models import (
    DataStatus,
    ObservationWindow,
    Provenance,
    SubjectRef,
)

Scalar: TypeAlias = str | int | float | bool


class EventType(str, Enum):
    __canonical_type_id__ = "sentinel.event_type"
    __canonical_type_version__ = "1"

    PRICE_LEVEL_INTERACTION = "PRICE_LEVEL_INTERACTION"
    PRICE_GAP = "PRICE_GAP"
    TREND_CHANGE = "TREND_CHANGE"
    ACTIVITY_ANOMALY = "ACTIVITY_ANOMALY"
    VOLATILITY_CHANGE = "VOLATILITY_CHANGE"
    RELATIVE_STRENGTH_CHANGE = "RELATIVE_STRENGTH_CHANGE"
    PARTICIPATION_CHANGE = "PARTICIPATION_CHANGE"
    RELATIONSHIP_CHANGE = "RELATIONSHIP_CHANGE"
    SERIES_STATE_CHANGE = "SERIES_STATE_CHANGE"


class EventDirection(str, Enum):
    __canonical_type_id__ = "sentinel.event_direction"
    __canonical_type_version__ = "1"

    CROSS_ABOVE = "CROSS_ABOVE"
    CROSS_BELOW = "CROSS_BELOW"
    TEST_FROM_ABOVE = "TEST_FROM_ABOVE"
    TEST_FROM_BELOW = "TEST_FROM_BELOW"
    REJECT_ABOVE = "REJECT_ABOVE"
    REJECT_BELOW = "REJECT_BELOW"
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"
    ELEVATED = "ELEVATED"
    DEPRESSED = "DEPRESSED"
    EXPANDING = "EXPANDING"
    CONTRACTING = "CONTRACTING"
    STRENGTHENING = "STRENGTHENING"
    WEAKENING = "WEAKENING"
    BROADENING = "BROADENING"
    NARROWING = "NARROWING"
    IMPROVING = "IMPROVING"
    DETERIORATING = "DETERIORATING"
    CONVERGING = "CONVERGING"
    DIVERGING = "DIVERGING"
    SYNCHRONIZING = "SYNCHRONIZING"
    DESYNCHRONIZING = "DESYNCHRONIZING"
    STEEPENING = "STEEPENING"
    FLATTENING = "FLATTENING"


class SemanticFlag(str, Enum):
    __canonical_type_id__ = "sentinel.semantic_flag"
    __canonical_type_version__ = "1"

    ANOMALOUS = "ANOMALOUS"
    DIVERGENT = "DIVERGENT"
    PROXY_BASED = "PROXY_BASED"


class EventLifecycle(str, Enum):
    __canonical_type_id__ = "sentinel.event_lifecycle"
    __canonical_type_version__ = "1"

    NEW = "NEW"
    CONTINUING = "CONTINUING"
    STRENGTHENED = "STRENGTHENED"
    WEAKENED = "WEAKENED"
    RESOLVED = "RESOLVED"
    REVERSED = "REVERSED"


_VALID_DIRECTIONS = {
    EventType.PRICE_LEVEL_INTERACTION: frozenset(
        {
            EventDirection.CROSS_ABOVE,
            EventDirection.CROSS_BELOW,
            EventDirection.TEST_FROM_ABOVE,
            EventDirection.TEST_FROM_BELOW,
            EventDirection.REJECT_ABOVE,
            EventDirection.REJECT_BELOW,
        }
    ),
    EventType.PRICE_GAP: frozenset({EventDirection.UP, EventDirection.DOWN}),
    EventType.TREND_CHANGE: frozenset(
        {EventDirection.UP, EventDirection.DOWN, EventDirection.NEUTRAL}
    ),
    EventType.ACTIVITY_ANOMALY: frozenset(
        {EventDirection.ELEVATED, EventDirection.DEPRESSED}
    ),
    EventType.VOLATILITY_CHANGE: frozenset(
        {
            EventDirection.EXPANDING,
            EventDirection.CONTRACTING,
            EventDirection.UP,
            EventDirection.DOWN,
        }
    ),
    EventType.RELATIVE_STRENGTH_CHANGE: frozenset(
        {EventDirection.STRENGTHENING, EventDirection.WEAKENING}
    ),
    EventType.PARTICIPATION_CHANGE: frozenset(
        {
            EventDirection.BROADENING,
            EventDirection.NARROWING,
            EventDirection.IMPROVING,
            EventDirection.DETERIORATING,
        }
    ),
    EventType.RELATIONSHIP_CHANGE: frozenset(
        {
            EventDirection.CONVERGING,
            EventDirection.DIVERGING,
            EventDirection.SYNCHRONIZING,
            EventDirection.DESYNCHRONIZING,
            EventDirection.STRENGTHENING,
            EventDirection.WEAKENING,
        }
    ),
    EventType.SERIES_STATE_CHANGE: frozenset(
        {
            EventDirection.UP,
            EventDirection.DOWN,
            EventDirection.STRENGTHENING,
            EventDirection.WEAKENING,
            EventDirection.IMPROVING,
            EventDirection.DETERIORATING,
            EventDirection.STEEPENING,
            EventDirection.FLATTENING,
        }
    ),
}


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class EvidenceLineage:
    """Identity of underlying observations shared by one or more facts."""

    __canonical_type_id__ = "sentinel.evidence_lineage"
    __canonical_type_version__ = "1"

    evidence_family: str
    source_observation_ids: tuple[str, ...]
    subject_ids: tuple[str, ...]
    baseline_id: str | None = None
    lineage_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.evidence_family, "evidence_family")
        if not self.source_observation_ids:
            raise ValueError("source_observation_ids must not be empty")
        if not self.subject_ids:
            raise ValueError("lineage subject_ids must not be empty")
        for value in (*self.source_observation_ids, *self.subject_ids):
            _require_text(value, "lineage identifier")
        if self.baseline_id is not None:
            _require_text(self.baseline_id, "baseline_id")
        object.__setattr__(
            self, "source_observation_ids", tuple(sorted(set(self.source_observation_ids)))
        )
        object.__setattr__(self, "subject_ids", tuple(sorted(set(self.subject_ids))))
        object.__setattr__(
            self,
            "lineage_id",
            stable_content_hash(
                {
                    "type": "sentinel.evidence_lineage",
                    "version": "1",
                    "evidence_family": self.evidence_family,
                    "source_observation_ids": self.source_observation_ids,
                    "subject_ids": self.subject_ids,
                    "baseline_id": self.baseline_id,
                }
            ),
        )


@dataclass(frozen=True)
class EventMagnitude:
    __canonical_type_id__ = "sentinel.event_magnitude"
    __canonical_type_version__ = "1"

    metric: str
    value: Scalar
    unit: str
    prior_value: Scalar | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    normalized_value: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.metric, "magnitude metric")
        _require_text(self.unit, "magnitude unit")


@dataclass(frozen=True)
class BaselineParameter:
    __canonical_type_id__ = "sentinel.baseline_parameter"
    __canonical_type_version__ = "1"

    name: str
    value: Scalar

    def __post_init__(self) -> None:
        _require_text(self.name, "baseline parameter name")


@dataclass(frozen=True)
class EventBaseline:
    """Baseline observation plus its stable semantic definition identity.

    ``baseline_id`` identifies the method/configuration (for example, a rolling
    20-session volume baseline), not the baseline's current measured value.
    Evolving measurements therefore remain occurrences in the same stream.
    """

    __canonical_type_id__ = "sentinel.event_baseline"
    __canonical_type_version__ = "1"

    baseline_id: str
    method: str
    comparison_window: ObservationWindow
    sample_count: int
    reference_value: Scalar | None = None
    reference_state: str | None = None
    dispersion: float | None = None
    parameters: tuple[BaselineParameter, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.baseline_id, "baseline_id")
        _require_text(self.method, "baseline method")
        if self.sample_count < 1:
            raise ValueError("baseline sample_count must be positive")
        if self.reference_state is not None:
            _require_text(self.reference_state, "reference_state")
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("baseline parameter names must be unique")
        object.__setattr__(self, "parameters", tuple(sorted(self.parameters, key=lambda p: p.name)))


@dataclass(frozen=True)
class EventEvidence:
    __canonical_type_id__ = "sentinel.event_evidence"
    __canonical_type_version__ = "1"

    metric: str
    subject_id: str
    value: Scalar
    unit: str
    window: ObservationWindow
    data_status: DataStatus
    lineage_id: str
    reference_value: Scalar | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.metric, "evidence metric")
        _require_text(self.subject_id, "evidence subject_id")
        _require_text(self.unit, "evidence unit")
        _require_text(self.lineage_id, "evidence lineage_id")
        if self.data_status is not DataStatus.AVAILABLE:
            raise ValueError("event evidence requires AVAILABLE data")
        if self.explanation is not None:
            _require_text(self.explanation, "evidence explanation")


@dataclass(frozen=True)
class SubjectRole:
    __canonical_type_id__ = "sentinel.subject_role"
    __canonical_type_version__ = "1"

    subject_id: str
    role: str

    def __post_init__(self) -> None:
        _require_text(self.subject_id, "relationship subject_id")
        _require_text(self.role, "relationship role")


@dataclass(frozen=True)
class EventRelationship:
    __canonical_type_id__ = "sentinel.event_relationship"
    __canonical_type_version__ = "1"

    relationship_kind: str
    subject_roles: tuple[SubjectRole, ...]
    expected_behavior: str
    observed_behavior: str
    comparison_window: ObservationWindow
    prior_strength: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.relationship_kind, "relationship_kind")
        _require_text(self.expected_behavior, "expected_behavior")
        _require_text(self.observed_behavior, "observed_behavior")
        if len(self.subject_roles) < 2:
            raise ValueError("relationship requires at least two subject roles")
        roles = [(item.role, item.subject_id) for item in self.subject_roles]
        if len(roles) != len(set(roles)):
            raise ValueError("relationship subject roles must be unique")
        object.__setattr__(
            self,
            "subject_roles",
            tuple(sorted(self.subject_roles, key=lambda item: (item.role, item.subject_id))),
        )


@dataclass(frozen=True)
class UniverseContext:
    __canonical_type_id__ = "sentinel.universe_context"
    __canonical_type_version__ = "1"

    tier: str
    universe_config_id: str
    membership_snapshot_id: str

    def __post_init__(self) -> None:
        _require_text(self.tier, "universe tier")
        _require_text(self.universe_config_id, "universe_config_id")
        _require_text(self.membership_snapshot_id, "membership_snapshot_id")


@dataclass(frozen=True)
class RelevanceContext:
    __canonical_type_id__ = "sentinel.relevance_context"
    __canonical_type_version__ = "1"

    is_holding: bool = False
    is_watchlist: bool = False
    is_discovered_outside_known_interest: bool = False
    activation_reason: str | None = None

    def __post_init__(self) -> None:
        if self.activation_reason is not None:
            _require_text(self.activation_reason, "activation_reason")


@dataclass(frozen=True)
class DetectedEvent:
    """One immutable, deterministic primitive market observation."""

    __canonical_type_id__ = "sentinel.detected_event"
    __canonical_type_version__ = "1"

    schema_version: str
    detector_id: str
    detector_version: str
    detector_config_id: ContentIdentity
    event_type: EventType
    observed_at: datetime
    observation_window: ObservationWindow
    subjects: tuple[SubjectRef, ...]
    economic_category: str
    direction: EventDirection
    magnitude: EventMagnitude
    baseline: EventBaseline
    evidence: tuple[EventEvidence, ...]
    evidence_lineage: tuple[EvidenceLineage, ...]
    provenance: tuple[Provenance, ...]
    universe_context: UniverseContext
    relevance_context: RelevanceContext = field(default_factory=RelevanceContext)
    semantic_flags: tuple[SemanticFlag, ...] = ()
    relationship: EventRelationship | None = None
    data_status: DataStatus = DataStatus.AVAILABLE
    event_id: str = field(init=False)
    deduplication_key: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.schema_version, "schema_version")
        _require_text(self.detector_id, "detector_id")
        _require_text(self.detector_version, "detector_version")
        _require_text(self.economic_category, "economic_category")
        _require_aware(self.observed_at, "observed_at")
        if self.detector_config_id.kind is not IdentityKind.CONFIGURATION:
            raise ValueError("detector_config_id must be a configuration identity")
        if not self.subjects:
            raise ValueError("event subjects must not be empty")
        subject_ids = [subject.subject_id for subject in self.subjects]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("event subject identities must be unique")
        object.__setattr__(self, "subjects", tuple(sorted(self.subjects, key=lambda item: item.subject_id)))
        if self.observation_window.end > self.observed_at:
            raise ValueError("observation window cannot end after observed_at")
        if not isinstance(self.event_type, EventType):
            raise TypeError("event_type must be an EventType")
        if not isinstance(self.direction, EventDirection):
            raise TypeError("direction must be an EventDirection")
        if self.direction not in _VALID_DIRECTIONS[self.event_type]:
            raise ValueError(f"{self.direction.value} is invalid for {self.event_type.value}")
        if self.event_type is EventType.SERIES_STATE_CHANGE and (
            "volatility" in self.economic_category.casefold()
            or "volatility" in self.magnitude.metric.casefold()
        ):
            raise ValueError("volatility-specific semantics require VOLATILITY_CHANGE")
        if not self.evidence:
            raise ValueError("event evidence must not be empty")
        if not self.evidence_lineage:
            raise ValueError("event evidence_lineage must not be empty")
        if not self.provenance:
            raise ValueError("event provenance must not be empty")
        if self.data_status is not DataStatus.AVAILABLE:
            raise ValueError("DetectedEvent requires AVAILABLE data")
        self._validate_references()
        self._validate_relationship()
        self._validate_proxy_semantics()
        object.__setattr__(
            self, "semantic_flags", tuple(sorted(set(self.semantic_flags), key=lambda flag: flag.value))
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(
                sorted(
                    self.evidence,
                    key=lambda item: (
                        item.metric,
                        item.subject_id,
                        item.lineage_id,
                        stable_content_hash(item),
                    ),
                )
            ),
        )
        object.__setattr__(
            self, "evidence_lineage", tuple(sorted(self.evidence_lineage, key=lambda item: item.lineage_id))
        )
        object.__setattr__(
            self,
            "provenance",
            tuple(
                sorted(
                    self.provenance,
                    key=lambda item: (
                        item.source_id,
                        item.source_record_id or "",
                        stable_content_hash(item),
                    ),
                )
            ),
        )
        object.__setattr__(self, "deduplication_key", stable_content_hash(self._stream_identity()))
        object.__setattr__(self, "event_id", stable_content_hash(self._occurrence_identity()))

    def _validate_references(self) -> None:
        subject_ids = {subject.subject_id for subject in self.subjects}
        lineage_by_id = {
            lineage.lineage_id: lineage
            for lineage in self.evidence_lineage
        }

        if any(item.subject_id not in subject_ids for item in self.evidence):
            raise ValueError("event evidence must reference an event subject")
        if any(item.lineage_id not in lineage_by_id for item in self.evidence):
            raise ValueError("event evidence must reference declared evidence lineage")
        if any(not set(lineage.subject_ids).issubset(subject_ids) for lineage in self.evidence_lineage):
            raise ValueError("evidence lineage subjects must be event subjects")

        for item in self.evidence:
            lineage = lineage_by_id[item.lineage_id]
            if item.subject_id not in lineage.subject_ids:
                raise ValueError(
                    "event evidence subject must belong to its referenced evidence lineage"
                )

    def _validate_relationship(self) -> None:
        if self.event_type is EventType.RELATIONSHIP_CHANGE and self.relationship is None:
            raise ValueError("RELATIONSHIP_CHANGE requires relationship context")
        if self.relationship is not None:
            subject_ids = {subject.subject_id for subject in self.subjects}
            role_subjects = {role.subject_id for role in self.relationship.subject_roles}
            if not role_subjects.issubset(subject_ids):
                raise ValueError("relationship roles must reference event subjects")

    def _validate_proxy_semantics(self) -> None:
        has_proxy = any(subject.proxy_for is not None for subject in self.subjects)
        has_proxy_flag = SemanticFlag.PROXY_BASED in self.semantic_flags
        if has_proxy != has_proxy_flag:
            raise ValueError("proxy subjects and PROXY_BASED semantic flag must be declared together")

    def _stream_identity(self) -> dict[str, object]:
        """Return only the stable definition of the phenomenon being tracked."""

        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "detector_config_id": self.detector_config_id,
            "subject_ids": tuple(subject.subject_id for subject in self.subjects),
            "proxy_for": tuple(subject.proxy_for for subject in self.subjects),
            "economic_category": self.economic_category,
            "timeframe": self.observation_window.timeframe,
            "baseline_id": self.baseline.baseline_id,
            "relationship_kind": (
                None if self.relationship is None else self.relationship.relationship_kind
            ),
            "relationship_roles": (
                () if self.relationship is None else self.relationship.subject_roles
            ),
            "universe_config_id": self.universe_context.universe_config_id,
        }

    def _occurrence_identity(self) -> dict[str, object]:
        return {
            "stream": self._stream_identity(),
            "direction": self.direction,
            "observed_at": self.observed_at,
            "observation_window": self.observation_window,
            "subjects": self.subjects,
            "magnitude": self.magnitude,
            "baseline": self.baseline,
            "evidence": self.evidence,
            "evidence_lineage": self.evidence_lineage,
            "semantic_flags": self.semantic_flags,
            "relationship": self.relationship,
            "universe_context": self.universe_context,
            "relevance_context": self.relevance_context,
            "data_status": self.data_status,
            "provenance": self.provenance,
        }
