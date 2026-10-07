"""Shared foundations for the read-only Sentinel subsystem."""

from dx27.intelligence.sentinel.identity import (
    ContentIdentity,
    IdentityKind,
    canonical_bytes,
    canonical_json,
    make_content_identity,
    stable_content_hash,
)
from dx27.intelligence.sentinel.events import (
    BaselineParameter,
    DetectedEvent,
    EventBaseline,
    EventDirection,
    EventEvidence,
    EventLifecycle,
    EventMagnitude,
    EventRelationship,
    EventType,
    EvidenceLineage,
    RelevanceContext,
    SemanticFlag,
    SubjectRole,
    UniverseContext,
)
from dx27.intelligence.sentinel.detection import DetectionResult
from dx27.intelligence.sentinel.detectors.activity import (
    ActivityAnomalyConfig,
    ActivityAnomalyDetector,
    ActivityAnomalyMeasurement,
)
from dx27.intelligence.sentinel.models import (
    DataStatus,
    ObservationWindow,
    Provenance,
    SubjectRef,
)
from dx27.intelligence.sentinel.observations import (
    ObservationCoverage,
    ObservationEnvelope,
)
from dx27.intelligence.sentinel.universe import (
    ContextualActivation,
    DiscoveryEligibility,
    DiscoveryRejectionReason,
    KnownInterestSnapshot,
    UniverseMembership,
    UniverseTier,
)

from dx27.intelligence.sentinel.market_state import MarketStateBuilder, SensorRegistry, StateBuild
from dx27.intelligence.sentinel.sensor_contracts import (
    FeedBinding, SeriesPoint, SensorDescriptor, SensorMeasurement,
    MarketStateSnapshot, VintageMode,
)
from dx27.intelligence.sentinel.sensor_inputs import (
    AvailabilityStamp, normalize_ohlcv_close, normalize_series_point,
)
from dx27.intelligence.sentinel.session_calendar import SessionCalendar, TradingSession
from dx27.intelligence.sentinel.state_projection import project_market_now

__all__ = [
    "MarketStateBuilder", "SensorRegistry", "StateBuild", "FeedBinding",
    "SeriesPoint", "SensorDescriptor", "SensorMeasurement", "MarketStateSnapshot",
    "VintageMode", "AvailabilityStamp", "normalize_ohlcv_close", "normalize_series_point",
    "SessionCalendar", "TradingSession", "project_market_now",
    "ActivityAnomalyConfig",
    "ActivityAnomalyDetector",
    "ActivityAnomalyMeasurement",
    "ContentIdentity",
    "ContextualActivation",
    "DataStatus",
    "DetectedEvent",
    "DiscoveryEligibility",
    "DiscoveryRejectionReason",
    "DetectionResult",
    "BaselineParameter",
    "EventBaseline",
    "EventDirection",
    "EventEvidence",
    "EventLifecycle",
    "EventMagnitude",
    "EventRelationship",
    "EventType",
    "EvidenceLineage",
    "IdentityKind",
    "KnownInterestSnapshot",
    "ObservationCoverage",
    "ObservationEnvelope",
    "ObservationWindow",
    "Provenance",
    "RelevanceContext",
    "SemanticFlag",
    "SubjectRole",
    "SubjectRef",
    "UniverseContext",
    "UniverseMembership",
    "UniverseTier",
    "canonical_bytes",
    "canonical_json",
    "make_content_identity",
    "stable_content_hash",
]
