"""Causal daily sensor measurement and dimension snapshots (6B-2H).

This module has no provider I/O, detectors, learned state labels, composite
scores or forecasts. Applications supply the pinned registry, calendar and
already normalized, versioned inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math
from statistics import stdev
from zoneinfo import ZoneInfo

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow
from dx27.intelligence.sentinel.sensor_contracts import (
    CoverageCount, DimensionState, FeedBinding, MarketStateSnapshot, Reliability,
    SectorValue, SensorDescriptor, SensorMeasurement, SeriesPoint, SnapshotCoverage, VintageMode,
)
from dx27.intelligence.sentinel.session_calendar import SessionCalendar, TradingSession

FROZEN_PROTOCOL_DIGEST = '18b21fc01c5776b6a9965262d6f6ca6efbd8197342c483589529257c5061a784'
_PRECEDENCE = (DataStatus.SOURCE_ERROR, DataStatus.UNSUPPORTED_SESSION, DataStatus.UNAVAILABLE,
               DataStatus.STALE, DataStatus.INSUFFICIENT_HISTORY, DataStatus.AVAILABLE)


def aggregate_status(statuses: tuple[DataStatus, ...]) -> DataStatus:
    return next((s for s in _PRECEDENCE if s in statuses), DataStatus.UNAVAILABLE)


@dataclass(frozen=True)
class FeedSpec:
    __canonical_type_id__ = 'sentinel.feed_spec'
    __canonical_type_version__ = '1'
    feed_id: str
    kind: str
    unit: str
    max_age_sessions: int


@dataclass(frozen=True)
class SensorSpec:
    __canonical_type_id__ = 'sentinel.sensor_spec'
    __canonical_type_version__ = '1'
    sensor_id: str
    dimension: str
    feeds: tuple[str, ...]
    method_id: str
    method_version: str
    unit: str
    lookback_sessions: int
    evidence_role: str
    redundancy_group: str
    activation: str
    required: bool


@dataclass(frozen=True)
class SensorRegistry:
    __canonical_type_id__ = 'sentinel.sensor_registry'
    __canonical_type_version__ = '1'
    protocol_digest: str
    feeds: tuple[FeedSpec, ...]
    sensors: tuple[SensorSpec, ...]
    dimensions: tuple[str, ...]

    def __post_init__(self) -> None:
        if stable_content_hash(self) != '19a5e5a03ef54fe8b9f881418c947117b2fdf291177188a1e25dbb4303cb36b1':
            raise ValueError('runtime registry differs from frozen protocol projection')

    @classmethod
    def from_protocol(cls, protocol: dict) -> SensorRegistry:
        if stable_content_hash(protocol) != FROZEN_PROTOCOL_DIGEST:
            raise ValueError('runtime requires the exact reviewed 6B-2G protocol')
        feeds = tuple(sorted((FeedSpec(f['feed_id'], f['kind'], f['normalized_unit'], f['max_age_sessions'])
                              for f in protocol['feeds']), key=lambda f: f.feed_id))
        sensors = tuple(sorted((SensorSpec(s['sensor_id'], s['dimension'], tuple(s['input_feed_ids']),
                        s['method_id'], s['method_version'], s['unit'], s['lookback_sessions'],
                        s['evidence_role'], s['redundancy_group'], s['activation'], s['required_for_dimension'])
                        for s in protocol['sensors']), key=lambda s: s.sensor_id))
        return cls(FROZEN_PROTOCOL_DIGEST, feeds, sensors, tuple(sorted(protocol['dimension_policy']['dimensions'])))


@dataclass(frozen=True)
class _Selection:
    status: DataStatus
    points: tuple[SeriesPoint, ...] = ()
    qualifiers: tuple[str, ...] = ()
    observation_session: str | None = None


@dataclass(frozen=True)
class StateBuild:
    """Snapshot plus its resolvable immutable evidence, including sector detail."""
    __canonical_type_id__ = 'sentinel.state_build'
    __canonical_type_version__ = '1'
    snapshot: MarketStateSnapshot
    descriptors: tuple[SensorDescriptor, ...]
    measurements: tuple[SensorMeasurement, ...]
    input_points: tuple[SeriesPoint, ...]
    sector_context: tuple[SensorMeasurement, ...] = ()

    def __post_init__(self) -> None:
        for name, kind, key in (('descriptors', SensorDescriptor, 'sensor_id'),
                                ('measurements', SensorMeasurement, 'sensor_id'),
                                ('input_points', SeriesPoint, 'point_id'),
                                ('sector_context', SensorMeasurement, 'measurement_id')):
            items = getattr(self, name)
            if not isinstance(items, tuple) or any(not isinstance(i, kind) for i in items):
                raise TypeError('immutable typed build tuples required')
            order = (lambda i: next((q.split(':',1)[1] for q in i.qualifiers if q.startswith('SECTOR_SUBJECT:')),
                                   next((q for q in i.qualifiers if q.startswith('SECTOR_FEED:')), i.measurement_id))) if name == 'sector_context' else (lambda i: getattr(i, key))
            object.__setattr__(self, name, tuple(sorted(items, key=order)))
        point_ids = {p.point_id for p in self.input_points}
        referenced_points = {i for m in self.measurements + self.sector_context for i in m.input_point_ids}
        if point_ids != referenced_points:
            raise ValueError('build must retain exactly resolved effective inputs')
        if len(point_ids) != len(self.input_points):
            raise ValueError('duplicate retained point')
        descriptors = {d.sensor_id: d for d in self.descriptors}
        by_id = {m.measurement_id: m for m in self.measurements}
        if len(descriptors) != len(self.descriptors) or len(by_id) != len(self.measurements):
            raise ValueError('duplicate build descriptor or measurement')
        if {m.sensor_id for m in self.measurements} != descriptors.keys() or len({m.sensor_id for m in self.measurements}) != len(self.measurements):
            raise ValueError('one measurement per descriptor required')
        if {d.dimension_id for d in self.snapshot.dimensions} != {d.dimension for d in self.descriptors}:
            raise ValueError('dimension coverage mismatch')
        expected_status = aggregate_status(tuple(m.data_status for m in self.measurements
                                                if descriptors[m.sensor_id].required_for_dimension))
        if expected_status is not self.snapshot.data_status:
            raise ValueError('snapshot status does not match required measurements')
        for dimension in self.snapshot.dimensions:
            members = tuple(m for m in self.measurements if descriptors[m.sensor_id].dimension == dimension.dimension_id)
            if set(dimension.measurement_ids) != {m.measurement_id for m in members}:
                raise ValueError('measurement in wrong dimension')
            if set(dimension.required_measurement_ids) != {m.measurement_id for m in members if descriptors[m.sensor_id].required_for_dimension}:
                raise ValueError('wrong required dimension inputs')
        referenced = {m for d in self.snapshot.dimensions for m in d.measurement_ids}
        if referenced != by_id.keys():
            raise ValueError('snapshot measurements must resolve exactly')
        points = {p.point_id: p for p in self.input_points}
        for measurement in self.measurements + self.sector_context:
            if not set(measurement.input_point_ids) <= point_ids:
                raise ValueError('unresolved measurement inputs')
            if measurement.sensor_id not in descriptors or measurement.descriptor_version != descriptors[measurement.sensor_id].descriptor_version:
                raise ValueError('unresolved descriptor version')
            descriptor = descriptors[measurement.sensor_id]
            if measurement.method_id != descriptor.method_id or measurement.method_version != descriptor.method_version or measurement.unit != descriptor.unit:
                raise ValueError('measurement method/unit differs from descriptor')
            if measurement.decision_cutoff != self.snapshot.decision_cutoff:
                raise ValueError('measurement cutoff differs from snapshot')
            actual = tuple(points[i] for i in measurement.input_point_ids)
            if set(measurement.lineage_ids) != {p.lineage_id for p in actual}:
                raise ValueError('measurement lineage does not match input points')
            if any(p.available_at > self.snapshot.decision_cutoff or p.observation_window.end > self.snapshot.decision_cutoff for p in actual):
                raise ValueError('build cannot contain future evidence')
            if actual and measurement.available_at != max(p.available_at for p in actual):
                raise ValueError('measurement availability must match its inputs')

    def measurement(self, sensor_id: str) -> SensorMeasurement:
        return next(m for m in self.measurements if m.sensor_id == sensor_id)


class MarketStateBuilder:
    def __init__(self, registry: SensorRegistry, calendar: SessionCalendar,
                 bindings: tuple[FeedBinding, ...],
                 vintage_mode: VintageMode = VintageMode.RECORDED_AS_AVAILABLE):
        if not isinstance(registry, SensorRegistry) or registry.protocol_digest != FROZEN_PROTOCOL_DIGEST:
            raise ValueError('pinned SensorRegistry required')
        if not isinstance(calendar, SessionCalendar) or not isinstance(vintage_mode, VintageMode):
            raise TypeError('typed calendar and vintage required')
        if not isinstance(bindings, tuple) or any(not isinstance(b, FeedBinding) for b in bindings):
            raise TypeError('immutable FeedBinding tuple required')
        if len({b.feed_id for b in bindings}) != len(bindings):
            raise ValueError('one versioned binding per feed role required')
        if len({b.subject_ref.subject_id for b in bindings}) != len(bindings):
            raise ValueError('distinct roles require distinct canonical subjects')
        specs = {f.feed_id: f for f in registry.feeds}
        for binding in bindings:
            if binding.feed_id not in specs or binding.normalized_unit != specs[binding.feed_id].unit:
                raise ValueError('binding role/unit does not match frozen registry')
            if specs[binding.feed_id].kind == 'ETF' and (binding.price_basis != 'TOTAL_RETURN_AS_AVAILABLE'
                  or binding.observation_label_policy != 'XNYS_SESSION' or binding.source_calendar_id != 'XNYS'):
                raise ValueError('ETF binding requires causal total-return price basis')
        self.registry, self.calendar, self.bindings, self.vintage_mode = registry, calendar, bindings, vintage_mode

    def _select(self, feed: FeedSpec, binding: FeedBinding | None,
                session: TradingSession, points: tuple[SeriesPoint, ...], cutoff: datetime) -> _Selection:
        if binding is None:
            return _Selection(DataStatus.UNAVAILABLE, qualifiers=('UNBOUND_FEED',))
        # Filter before inspecting revisions, payloads or missingness: appending
        # future records must not alter any previously emitted result/identity.
        def label(point):
            zone = timezone.utc if binding.observation_label_policy == 'UTC_DATE_BEFORE_EXCLUSIVE_END' else ZoneInfo('America/New_York')
            end = point.observation_window.end.astimezone(zone)
            if binding.observation_label_policy.endswith('BEFORE_EXCLUSIVE_END'):
                return (end.date()-timedelta(days=1)).isoformat()
            return end.date().isoformat()
        candidates = {p.point_id: p for p in points if p.subject_ref.subject_id == binding.subject_ref.subject_id
                      and p.available_at <= cutoff and p.observation_window.end <= cutoff and label(p) <= session.session_id}
        if not candidates:
            started_later = any(p.subject_ref.subject_id == binding.subject_ref.subject_id
                                and p.available_at <= cutoff and label(p) > session.session_id for p in points)
            return _Selection(DataStatus.INSUFFICIENT_HISTORY if started_later else DataStatus.UNAVAILABLE,
                              qualifiers=('HISTORY_NOT_YET_STARTED' if started_later else 'MISSING_INPUT',))
        latest_day = max(label(p) for p in candidates.values())
        candidates = tuple(p for p in candidates.values() if label(p) == latest_day)
        availability = max(p.available_at for p in candidates)
        candidates = tuple(p for p in candidates if p.available_at == availability)
        if len(candidates) > 1 and binding.revision_order == 'NUMERIC':
            if any(not p.revision_id.isdecimal() for p in candidates):
                return _Selection(DataStatus.SOURCE_ERROR, tuple(sorted(candidates, key=lambda p: p.point_id)), ('INVALID_REVISION_SEQUENCE',))
            seq = max(int(p.revision_id) for p in candidates)
            candidates = tuple(p for p in candidates if int(p.revision_id) == seq)
        if len(candidates) != 1:
            return _Selection(DataStatus.SOURCE_ERROR, tuple(sorted(candidates, key=lambda p: p.point_id)), ('AMBIGUOUS_REVISION',))
        point = candidates[0]
        if (point.subject_ref != binding.subject_ref or point.source_id != binding.source_id
                or point.source_version != binding.source_version or point.unit != binding.normalized_unit):
            return _Selection(DataStatus.SOURCE_ERROR, (point,), ('SOURCE_BINDING_MISMATCH',))
        if point.vintage_mode is not self.vintage_mode:
            return _Selection(DataStatus.UNAVAILABLE, (point,), ('VINTAGE_MODE_MISMATCH',))
        try:
            day = label(point)
            self.calendar.age_of_date(day, session.session_id)
            observed = self.calendar.get(day) if binding.observation_label_policy == 'XNYS_SESSION' or binding.source_calendar_id == 'XNYS' else None
        except ValueError:
            return _Selection(DataStatus.UNSUPPORTED_SESSION, (point,), ('UNSUPPORTED_OBSERVATION_SESSION',))
        window = point.observation_window
        bad_window = window.timeframe != '1d'
        if binding.observation_label_policy == 'XNYS_SESSION':
            bad_window |= window.start != observed.opens_at or window.end != observed.closes_at
        elif binding.observation_label_policy.endswith('BEFORE_EXCLUSIVE_END'):
            zone = timezone.utc if binding.observation_label_policy.startswith('UTC') else ZoneInfo('America/New_York')
            start, end = window.start.astimezone(zone), window.end.astimezone(zone)
            bad_window |= (end.hour, end.minute, end.second, end.microsecond) != (0,0,0,0)
            bad_window |= (start.hour, start.minute, start.second, start.microsecond) != (0,0,0,0)
            bad_window |= start.date().isoformat() != day or (end.date()-start.date()).days != 1
        else:
            bad_window |= window.start.astimezone(ZoneInfo('America/New_York')).date().isoformat() != day
        if bad_window:
            return _Selection(DataStatus.UNSUPPORTED_SESSION, (point,), ('SESSION_WINDOW_MISMATCH',))
        faults = [point.data_status]
        reasons = []
        if point.data_status is DataStatus.AVAILABLE and point.available_at < point.observation_window.end:
            faults.append(DataStatus.SOURCE_ERROR)
            reasons.append('CAPTURE_BEFORE_OBSERVATION_COMPLETE')
        age = self.calendar.age_of_date(day, session.session_id)
        if day not in {s.session_id for s in self.calendar.sessions}:
            reasons.append('SOURCE_NON_XNYS_DATE')
        if age > feed.max_age_sessions:
            faults.append(DataStatus.STALE)
            reasons.append('STALE_INPUT')
        elif age:
            reasons.append('LAGGED_INPUT')
        if point.data_status is not DataStatus.AVAILABLE:
            reasons.append('SOURCE_' + point.data_status.value)
        if point.value is not None and ((feed.kind == 'ETF' and point.value <= 0) or
                                        (feed.feed_id in {'vix', 'hy_oas'} and point.value < 0)):
            faults.append(DataStatus.SOURCE_ERROR)
            reasons.append('INVALID_VALUE_DOMAIN')
        if binding.revision_order == 'NUMERIC' and not point.revision_id.isdecimal():
            faults.append(DataStatus.SOURCE_ERROR)
            reasons.append('INVALID_REVISION_SEQUENCE')
        if point.vintage_mode is VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY:
            reasons.append('DESCRIPTIVE_ONLY')
        return _Selection(aggregate_status(tuple(faults)), (point,), tuple(reasons), day)

    def build(self, session_id: str, points: tuple[SeriesPoint, ...]) -> StateBuild:
        if not isinstance(points, tuple) or any(not isinstance(p, SeriesPoint) for p in points):
            raise TypeError('immutable SeriesPoint tuple required')
        session = self.calendar.get(session_id)
        bindings = {b.feed_id: b for b in self.bindings if b.validated_at <= session.decision_cutoff}
        feeds = {f.feed_id: f for f in self.registry.feeds}
        # Cache per-feed/per-observation selection within this cutoff. Warmup
        # uses revisions available at THIS cutoff, not a later full-data view.
        cache = {}
        def select(feed_id: str, observation: TradingSession) -> _Selection:
            key = (feed_id, observation.session_id)
            if key not in cache:
                cache[key] = self._select(feeds[feed_id], bindings.get(feed_id), observation, eligible, session.decision_cutoff)
            return cache[key]
        eligible = tuple(p for p in points if p.available_at <= session.decision_cutoff
                         and p.observation_window.end <= session.decision_cutoff)
        descriptors, measurements, sector_context = [], [], []
        evidence = {}
        for spec in self.registry.sensors:
            bound = tuple(bindings[f] for f in spec.feeds if f in bindings)
            proxy_for = ('participation_weighting_divergence_not_constituent_breadth' if spec.dimension == 'participation'
                         else spec.sensor_id + '_economic_role_proxy') if spec.evidence_role == 'PROXY' else None
            descriptor = SensorDescriptor(spec.sensor_id, tuple(b.subject_ref for b in bound), spec.dimension,
                       spec.unit, spec.evidence_role, proxy_for, spec.redundancy_group, spec.method_id,
                       spec.method_version, spec.lookback_sessions, spec.required, spec.activation,
                       stable_content_hash(tuple(sorted(b.binding_version for b in bound)))
                       if bound and len(bound) == len(spec.feeds) else None)
            descriptors.append(descriptor)
            qualifiers = ['PROXY_ONLY'] if spec.evidence_role == 'PROXY' else []
            if self.vintage_mode is VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY:
                qualifiers.append('DESCRIPTIVE_ONLY')
            if spec.activation == 'BLOCKED_PIT_INPUTS':
                measurement = self._measurement(descriptor, session, DataStatus.UNAVAILABLE, None, (),
                                                tuple(qualifiers + ['BLOCKED_PIT_INPUTS']), 0)
            elif spec.method_id == 'sector_relative_vector_20':
                members = []
                for feed_id in spec.feeds[:-1]:
                    m = self._scalar(descriptor, session, (feed_id, 'spy'), 'relative_log_return_20', select,
                                     tuple(qualifiers + ['SECTOR_MEMBER_CONTEXT']))
                    detail = replace(m[0], qualifiers=m[0].qualifiers + ('SECTOR_FEED:' + feed_id,) +
                                     (('SECTOR_SUBJECT:' + bindings[feed_id].subject_ref.subject_id,) if feed_id in bindings else ()))
                    sector_context.append(detail)
                    for p in m[1]:
                        evidence[p.point_id] = p
                    members.append((feed_id, m[0], m[1], m[2]))
                all_points = tuple({p.point_id: p for _, _, ps, _ in members for p in ps}.values())
                status = aggregate_status(tuple(m.data_status for _, m, _, _ in members))
                if status is not DataStatus.AVAILABLE:
                    sector_context[-len(members):] = [replace(m, qualifiers=m.qualifiers + ('PARTIAL_SECTOR_CONTEXT',))
                                                    for m in sector_context[-len(members):]]
                value = tuple(SectorValue(bindings[f].subject_ref.subject_id, m.value[0].value) for f, m, _, _ in members) if status is DataStatus.AVAILABLE else None
                measurement = self._measurement(descriptor, session, status, value, all_points,
                                      tuple(qualifiers + ([] if status is DataStatus.AVAILABLE else ['INCOMPLETE_SECTOR_VECTOR'])), 210,
                                      len({i for _, _, _, ids in members for i in ids}))
            else:
                measurement, selected, _ = self._scalar(descriptor, session, spec.feeds, spec.method_id, select, tuple(qualifiers))
                for p in selected:
                    evidence[p.point_id] = p
            measurements.append(measurement)
        sector_detail = tuple(sector_context)
        measures = tuple(sorted(measurements, key=lambda m: m.sensor_id))
        by_sensor = {m.sensor_id: m for m in measures}
        dimensions = []
        for dimension in self.registry.dimensions:
            specs = tuple(s for s in self.registry.sensors if s.dimension == dimension)
            required = tuple(by_sensor[s.sensor_id] for s in specs if s.required)
            evaluated = required or tuple(by_sensor[s.sensor_id] for s in specs if s.activation != 'BLOCKED_PIT_INPUTS')
            qualifiers = ('PROXY_ONLY', 'TRUE_BREADTH_UNAVAILABLE', 'CONCENTRATION_UNAVAILABLE') if dimension == 'participation' else ()
            dimensions.append(DimensionState(dimension, aggregate_status(tuple(m.data_status for m in evaluated)),
                            tuple(by_sensor[s.sensor_id].measurement_id for s in specs),
                            tuple(m.measurement_id for m in required), qualifiers))
        def counts(activation: str | None) -> CoverageCount:
            selected = tuple(s for s in self.registry.sensors if activation is None or s.activation == activation)
            return CoverageCount(len(selected), sum(by_sensor[s.sensor_id].data_status is DataStatus.AVAILABLE for s in selected))
        registered = counts(None)
        coverage = SnapshotCoverage(registered, counts('ACTIVE_CONTRACT'), counts('OPTIONAL_CONTRACT'), counts('BLOCKED_PIT_INPUTS'),
                                   'COMPLETE' if registered.available == registered.expected else 'PARTIAL' if registered.available else 'UNAVAILABLE')
        relationships = tuple(by_sensor[s.sensor_id].measurement_id for s in self.registry.sensors
                              if s.method_id in {'relative_log_return_20', 'yield_slope', 'funding_spread', 'implied_minus_realized_20'})
        snapshot = MarketStateSnapshot('1', self.registry.protocol_digest, session.decision_cutoff, session_id,
                    self.calendar.calendar_version, self.vintage_mode, tuple(dimensions), relationships, coverage,
                    aggregate_status(tuple(by_sensor[s.sensor_id].data_status for s in self.registry.sensors if s.required)))
        return StateBuild(snapshot, tuple(descriptors), measures, tuple(sorted(evidence.values(), key=lambda p: p.point_id)),
                          tuple(sorted(sector_detail, key=lambda m: m.measurement_id)))

    def _measurement(self, descriptor: SensorDescriptor, session: TradingSession, status: DataStatus,
                     value, points: tuple[SeriesPoint, ...], qualifiers: tuple[str, ...], required: int, usable: int = 0) -> SensorMeasurement:
        points = tuple({p.point_id: p for p in points}.values())
        start = min((p.observation_window.start for p in points), default=session.opens_at)
        end = max((p.observation_window.end for p in points), default=session.closes_at)
        return SensorMeasurement(descriptor.sensor_id, descriptor.descriptor_version, descriptor.method_id,
                   descriptor.method_version, ObservationWindow(start, end, '1d'), session.decision_cutoff,
                   max((p.available_at for p in points), default=None), status, value if status is DataStatus.AVAILABLE else None,
                   descriptor.unit, tuple(p.point_id for p in points), tuple(p.lineage_id for p in points), qualifiers,
                   Reliability(usable, required))

    def _scalar(self, descriptor: SensorDescriptor, session: TradingSession, feed_ids: tuple[str, ...], method: str,
                select, qualifiers: tuple[str, ...]) -> tuple[SensorMeasurement, tuple[SeriesPoint, ...], tuple[str, ...]]:
        length = 21 if method in {'log_return_20', 'relative_log_return_20', 'sample_rv_20',
                                 'rv_ratio_5_20', 'implied_minus_realized_20'} else 1
        history = self.calendar.history(session.session_id, length)
        selected = {}
        usable_ids = set()
        statuses, reasons = [], list(qualifiers)
        series = {}
        labels = {}
        required = (21 + 1 if method == 'implied_minus_realized_20' else length * len(feed_ids))
        if len(history) < length:
            statuses.append(DataStatus.INSUFFICIENT_HISTORY)
            reasons.append('CALENDAR_WARMUP_TOO_SHORT')
        for feed_id in feed_ids:
            sessions = history if feed_id not in {'vix'} or method != 'implied_minus_realized_20' else (session,)
            values = []
            dates = []
            for observed in sessions:
                result = select(feed_id, observed)
                statuses.append(result.status)
                dates.append(result.observation_session)
                reasons.extend(result.qualifiers)
                for p in result.points:
                    selected[p.point_id] = p
                    if result.status is DataStatus.AVAILABLE:
                        usable_ids.add(p.point_id)
                values.append(result.points[0] if result.status is DataStatus.AVAILABLE else None)
            series[feed_id] = values
            labels[feed_id] = dates
        status = aggregate_status(tuple(statuses))
        points = tuple(selected.values())
        # Inputs for one-value derived spreads must describe the same session.
        if status is DataStatus.AVAILABLE and method in {'yield_slope', 'funding_spread', 'implied_minus_realized_20'}:
            ends = {labels[f][-1] for f in feed_ids}
            if len(ends) != 1:
                status = DataStatus.UNAVAILABLE
                reasons.append('MISALIGNED_OBSERVATION_SESSIONS')
        value = None
        if status is DataStatus.AVAILABLE:
            def returns(feed: str) -> list[float]:
                return [math.log(b.value) - math.log(a.value) for a, b in zip(series[feed], series[feed][1:])]
            def ret(feed: str) -> float:
                return math.log(series[feed][-1].value) - math.log(series[feed][0].value)
            if method == 'log_return_20':
                value = ret(feed_ids[0])
            elif method == 'relative_log_return_20':
                value = ret(feed_ids[0]) - ret(feed_ids[1])
            elif method == 'sample_rv_20':
                value = 100 * math.sqrt(252) * stdev(returns(feed_ids[0]))
            elif method == 'rv_ratio_5_20':
                values = returns(feed_ids[0])
                denom = stdev(values)
                if denom == 0:
                    status = DataStatus.INSUFFICIENT_HISTORY
                    reasons.append('ZERO_VARIANCE_DENOMINATOR')
                else:
                    value = stdev(values[-5:]) / denom
            elif method == 'latest_point':
                value = series[feed_ids[0]][-1].value
            elif method == 'implied_minus_realized_20':
                value = series['vix'][-1].value - 100 * math.sqrt(252) * stdev(returns('spy'))
            elif method == 'yield_slope':
                value = 100 * (series['ust_10y'][-1].value - series['ust_2y'][-1].value)
            elif method == 'funding_spread':
                value = 100 * (series['sofr'][-1].value - series['effr'][-1].value)
            else:
                raise ValueError('unimplemented registered method')
            if value is not None and not math.isfinite(value):
                status = DataStatus.SOURCE_ERROR
                reasons.append('NONFINITE_DERIVED_VALUE')
        if descriptor.method_id == 'sector_relative_vector_20' and status is DataStatus.AVAILABLE:
            value = (SectorValue(series[feed_ids[0]][-1].subject_ref.subject_id, value),)
        return self._measurement(descriptor, session, status, value, points, tuple(reasons), required, len(usable_ids)), points, tuple(sorted(usable_ids))
