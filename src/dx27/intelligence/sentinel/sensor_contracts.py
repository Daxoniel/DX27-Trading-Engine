"""Immutable multi-sensor input and state contracts; no scores or forecasts."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum
import math

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow, SubjectRef, _require_text
from dx27.intelligence.sentinel.session_calendar import utc


def content_id(obj: object, id_field: str) -> str:
    return stable_content_hash({'type': obj.__canonical_type_id__, 'version': obj.__canonical_type_version__,
                                'fields': {f.name: getattr(obj, f.name) for f in fields(obj) if f.name != id_field}})


def _number(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('value must be a finite number')


def _digest(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('expected lowercase SHA256 digest')


def _texts(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError('immutable tuple required')
    for value in values:
        _require_text(value, 'reference')
    return tuple(sorted(set(values)))


def _window(window: ObservationWindow) -> ObservationWindow:
    if not isinstance(window, ObservationWindow):
        raise TypeError('ObservationWindow required')
    return ObservationWindow(utc(window.start), utc(window.end), window.timeframe, window.completed)


class VintageMode(str, Enum):
    __canonical_type_id__ = 'sentinel.vintage_mode'
    __canonical_type_version__ = '1'
    RECORDED_AS_AVAILABLE = 'RECORDED_AS_AVAILABLE'
    LATEST_VINTAGE_DESCRIPTIVE_ONLY = 'LATEST_VINTAGE_DESCRIPTIVE_ONLY'


@dataclass(frozen=True)
class FeedBinding:
    """Validated role-to-source metadata, supplied at the application boundary.

    This record is not a validation service: the referenced source metadata must
    actually have been checked. Fixture bindings must remain labelled as fixtures.
    """
    __canonical_type_id__ = 'sentinel.feed_binding'
    __canonical_type_version__ = '1'
    feed_id: str
    subject_ref: SubjectRef
    source_id: str
    source_version: str
    raw_unit: str
    normalized_unit: str
    validation_record_id: str
    validated_at: datetime
    source_calendar_id: str
    price_basis: str = 'NOT_PRICE'
    revision_order: str = 'OPAQUE'
    observation_label_policy: str = 'LOCAL_DATE_OF_END'
    binding_version: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ('feed_id', 'source_id', 'source_version', 'raw_unit', 'normalized_unit', 'validation_record_id', 'source_calendar_id'):
            _require_text(getattr(self, name), name)
        if not isinstance(self.subject_ref, SubjectRef):
            raise TypeError('SubjectRef required')
        object.__setattr__(self, 'validated_at', utc(self.validated_at))
        if self.price_basis not in {'NOT_PRICE', 'TOTAL_RETURN_AS_AVAILABLE'}:
            raise ValueError('price basis must be explicit and causal')
        if self.observation_label_policy not in {'XNYS_SESSION', 'LOCAL_DATE_OF_END',
                  'LOCAL_DATE_BEFORE_EXCLUSIVE_END', 'UTC_DATE_BEFORE_EXCLUSIVE_END'}:
            raise ValueError('explicit observation label policy required')
        if self.revision_order not in {'OPAQUE', 'NUMERIC'}:
            raise ValueError('revision order must be OPAQUE or NUMERIC')
        if self.raw_unit != self.normalized_unit and not (
            self.raw_unit in {'percent', 'percent_per_annum'} and self.normalized_unit == 'basis_points'
        ):
            raise ValueError('unsupported unit conversion')
        object.__setattr__(self, 'binding_version', content_id(self, 'binding_version'))

    def normalize(self, value: float) -> float:
        _number(value)
        return float(value) * (100 if self.raw_unit != self.normalized_unit else 1)


@dataclass(frozen=True)
class SeriesPoint:
    __canonical_type_id__ = 'sentinel.series_point'
    __canonical_type_version__ = '1'
    subject_ref: SubjectRef
    observation_window: ObservationWindow
    data_status: DataStatus
    value: float | None
    unit: str
    published_at: datetime | None
    first_seen_at: datetime
    source_id: str
    source_record_id: str
    source_version: str
    revision_id: str
    payload_sha256: str
    vintage_mode: VintageMode = VintageMode.RECORDED_AS_AVAILABLE
    point_id: str = field(init=False)
    available_at: datetime = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.subject_ref, SubjectRef) or not isinstance(self.data_status, DataStatus):
            raise TypeError('typed subject and data status required')
        if not isinstance(self.vintage_mode, VintageMode):
            raise TypeError('typed vintage mode required')
        for name in ('unit', 'source_id', 'source_record_id', 'source_version', 'revision_id'):
            _require_text(getattr(self, name), name)
        _digest(self.payload_sha256)
        object.__setattr__(self, 'observation_window', _window(self.observation_window))
        object.__setattr__(self, 'first_seen_at', utc(self.first_seen_at))
        if self.published_at is not None:
            object.__setattr__(self, 'published_at', utc(self.published_at))
        object.__setattr__(self, 'available_at', max(self.first_seen_at, self.published_at or self.first_seen_at))
        if self.data_status is DataStatus.AVAILABLE:
            _number(self.value)
            object.__setattr__(self, 'value', float(self.value))
        elif self.value is not None:
            raise ValueError('non-AVAILABLE points must have null value')
        object.__setattr__(self, 'point_id', content_id(self, 'point_id'))

    @property
    def lineage_id(self) -> str:
        # Revisions of one source observation share lineage; measurements using
        # the same SPY history cannot present it as independent confirmation.
        return stable_content_hash({'subject': self.subject_ref.subject_id, 'source': self.source_id,
                                    'record': self.source_record_id, 'window': self.observation_window})


@dataclass(frozen=True)
class SensorDescriptor:
    __canonical_type_id__ = 'sentinel.sensor_descriptor'
    __canonical_type_version__ = '1'
    sensor_id: str
    subject_refs: tuple[SubjectRef, ...]
    dimension: str
    unit: str
    evidence_role: str
    proxy_for: str | None
    redundancy_group: str
    method_id: str
    method_version: str
    lookback_sessions: int
    required_for_dimension: bool
    activation: str
    source_binding_version: str | None

    def __post_init__(self) -> None:
        for name in ('sensor_id', 'dimension', 'unit', 'redundancy_group', 'method_id', 'method_version'):
            _require_text(getattr(self, name), name)
        if self.evidence_role not in {'DIRECT', 'PROXY'}:
            raise ValueError('invalid evidence role')
        if self.evidence_role == 'PROXY':
            _require_text(self.proxy_for, 'proxy_for')
        elif self.proxy_for is not None:
            raise ValueError('DIRECT measurement has no proxy_for')
        if not isinstance(self.subject_refs, tuple) or any(not isinstance(s, SubjectRef) for s in self.subject_refs):
            raise TypeError('immutable subject references required')
        refs = tuple(sorted(set(self.subject_refs), key=lambda s: (s.subject_id, stable_content_hash(s))))
        if len({s.subject_id for s in refs}) != len(refs):
            raise ValueError('conflicting metadata for canonical subject')
        object.__setattr__(self, 'subject_refs', refs)
        if type(self.lookback_sessions) is not int or self.lookback_sessions < 0:
            raise ValueError('invalid lookback')
        if type(self.required_for_dimension) is not bool:
            raise TypeError('required_for_dimension must be bool')
        if self.source_binding_version is not None:
            _digest(self.source_binding_version)

    @property
    def descriptor_version(self) -> str:
        return '1:' + stable_content_hash(self)


@dataclass(frozen=True)
class Reliability:
    __canonical_type_id__ = 'sentinel.sensor_reliability'
    __canonical_type_version__ = '1'
    usable_points: int
    required_points: int
    validation_record_id: str | None = None

    def __post_init__(self) -> None:
        if any(type(v) is not int for v in (self.usable_points, self.required_points)):
            raise TypeError('integer support counts required')
        if not 0 <= self.usable_points <= self.required_points:
            raise ValueError('invalid support counts')
        if self.validation_record_id is not None:
            _require_text(self.validation_record_id, 'validation_record_id')


@dataclass(frozen=True)
class SectorValue:
    __canonical_type_id__ = 'sentinel.sector_value'
    __canonical_type_version__ = '1'
    subject_id: str
    value: float

    def __post_init__(self) -> None:
        _require_text(self.subject_id, 'subject_id')
        _number(self.value)
        object.__setattr__(self, 'value', float(self.value))


@dataclass(frozen=True)
class SensorMeasurement:
    __canonical_type_id__ = 'sentinel.sensor_measurement'
    __canonical_type_version__ = '1'
    sensor_id: str
    descriptor_version: str
    method_id: str
    method_version: str
    observation_window: ObservationWindow
    decision_cutoff: datetime
    available_at: datetime | None
    data_status: DataStatus
    value: float | tuple[SectorValue, ...] | None
    unit: str
    input_point_ids: tuple[str, ...]
    lineage_ids: tuple[str, ...]
    qualifiers: tuple[str, ...]
    reliability: Reliability
    measurement_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ('sensor_id', 'descriptor_version', 'method_id', 'method_version', 'unit'):
            _require_text(getattr(self, name), name)
        if not isinstance(self.data_status, DataStatus) or not isinstance(self.reliability, Reliability):
            raise TypeError('typed status and reliability required')
        object.__setattr__(self, 'decision_cutoff', utc(self.decision_cutoff))
        object.__setattr__(self, 'observation_window', _window(self.observation_window))
        if self.observation_window.end > self.decision_cutoff:
            raise ValueError('measurement observation cannot follow cutoff')
        if self.available_at is not None:
            object.__setattr__(self, 'available_at', utc(self.available_at))
            if self.available_at > self.decision_cutoff:
                raise ValueError('measurement cannot use future availability')
        for name in ('input_point_ids', 'lineage_ids', 'qualifiers'):
            object.__setattr__(self, name, _texts(getattr(self, name)))
        if self.data_status is DataStatus.AVAILABLE:
            if self.available_at is None or not self.input_point_ids or not self.lineage_ids:
                raise ValueError('AVAILABLE requires available inputs and lineage')
            if self.method_id == 'sector_relative_vector_20':
                if not isinstance(self.value, tuple):
                    raise ValueError('sector method requires typed vector')
                expected_size = 1 if 'SECTOR_MEMBER_CONTEXT' in self.qualifiers else 9
                if len(self.value) != expected_size:
                    raise ValueError('sector vector cardinality mismatch')
                if not self.value or any(not isinstance(v, SectorValue) for v in self.value):
                    raise ValueError('nonempty typed sector vector required')
                vector = tuple(sorted(self.value, key=lambda v: v.subject_id))
                if len({v.subject_id for v in vector}) != len(vector):
                    raise ValueError('duplicate sector member')
                object.__setattr__(self, 'value', vector)
            else:
                _number(self.value)
                object.__setattr__(self, 'value', float(self.value))
        elif self.value is not None:
            raise ValueError('non-AVAILABLE measurement must have null value')
        object.__setattr__(self, 'measurement_id', content_id(self, 'measurement_id'))


@dataclass(frozen=True)
class DimensionState:
    __canonical_type_id__ = 'sentinel.dimension_state'
    __canonical_type_version__ = '1'
    dimension_id: str
    data_status: DataStatus
    measurement_ids: tuple[str, ...]
    required_measurement_ids: tuple[str, ...]
    qualifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.dimension_id, 'dimension_id')
        if not isinstance(self.data_status, DataStatus):
            raise TypeError('DataStatus required')
        for name in ('measurement_ids', 'required_measurement_ids', 'qualifiers'):
            object.__setattr__(self, name, _texts(getattr(self, name)))
        if not set(self.required_measurement_ids) <= set(self.measurement_ids):
            raise ValueError('required measurement outside dimension')


@dataclass(frozen=True)
class CoverageCount:
    __canonical_type_id__ = 'sentinel.coverage_count'
    __canonical_type_version__ = '1'
    expected: int
    available: int

    def __post_init__(self) -> None:
        if type(self.expected) is not int or type(self.available) is not int or not 0 <= self.available <= self.expected:
            raise ValueError('invalid coverage counts')


@dataclass(frozen=True)
class SnapshotCoverage:
    __canonical_type_id__ = 'sentinel.snapshot_coverage'
    __canonical_type_version__ = '1'
    registered: CoverageCount
    active_required: CoverageCount
    optional: CoverageCount
    blocked: CoverageCount
    grade: str

    def __post_init__(self) -> None:
        counts = (self.active_required, self.optional, self.blocked)
        if not isinstance(self.registered, CoverageCount) or any(not isinstance(c, CoverageCount) for c in counts):
            raise TypeError('typed coverage counts required')
        if self.registered.expected != sum(c.expected for c in counts) or self.registered.available != sum(c.available for c in counts):
            raise ValueError('coverage partition mismatch')
        expected_grade = 'COMPLETE' if self.registered.available == self.registered.expected else (
            'PARTIAL' if self.registered.available else 'UNAVAILABLE')
        if self.grade != expected_grade:
            raise ValueError('coverage grade must describe actual registered coverage')


@dataclass(frozen=True)
class MarketStateSnapshot:
    __canonical_type_id__ = 'sentinel.market_state_snapshot'
    __canonical_type_version__ = '1'
    schema_version: str
    protocol_digest: str
    decision_cutoff: datetime
    session_id: str
    calendar_version: str
    vintage_mode: VintageMode
    dimensions: tuple[DimensionState, ...]
    relationships: tuple[str, ...]
    coverage: SnapshotCoverage
    data_status: DataStatus
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ('schema_version', 'session_id', 'calendar_version'):
            _require_text(getattr(self, name), name)
        _digest(self.protocol_digest)
        object.__setattr__(self, 'decision_cutoff', utc(self.decision_cutoff))
        if not isinstance(self.data_status, DataStatus) or not isinstance(self.vintage_mode, VintageMode):
            raise TypeError('typed state and vintage required')
        if not isinstance(self.dimensions, tuple) or any(not isinstance(d, DimensionState) for d in self.dimensions):
            raise TypeError('immutable dimension states required')
        if not isinstance(self.coverage, SnapshotCoverage):
            raise TypeError('SnapshotCoverage required')
        if (self.data_status is DataStatus.AVAILABLE) != (self.coverage.active_required.available == self.coverage.active_required.expected):
            raise ValueError('snapshot status must match required coverage')
        dims = tuple(sorted(self.dimensions, key=lambda d: d.dimension_id))
        if len({d.dimension_id for d in dims}) != len(dims):
            raise ValueError('duplicate dimension')
        object.__setattr__(self, 'dimensions', dims)
        object.__setattr__(self, 'relationships', _texts(self.relationships))
        if not set(self.relationships) <= {m for d in dims for m in d.measurement_ids}:
            raise ValueError('relationship measurement outside snapshot')
        object.__setattr__(self, 'snapshot_id', content_id(self, 'snapshot_id'))
