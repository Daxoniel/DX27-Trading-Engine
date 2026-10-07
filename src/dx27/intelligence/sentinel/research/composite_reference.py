"""Frozen 6B-2I causal references. Research only; no report/priority activation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from statistics import median

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.market_state import StateBuild, FROZEN_PROTOCOL_DIGEST, aggregate_status
from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.sensor_contracts import VintageMode, _number
from dx27.intelligence.sentinel.session_calendar import SessionCalendar, utc

PRESSURE = 'us-equity-pressure-3g-v1'
DIVERGENCE = 'us-equity-divergence-2p-v1'
GROUPS = (('equity_weakness', (('spy_return_20', .5), ('rsp_return_20', .5)), True),
          ('volatility', (('spy_rv_20', .5), ('vix_level', .5)), False),
          ('credit', (('hy_oas_level', 1.),), False))
PAIRS = ('rsp_spy_relative_20', 'qqq_spy_relative_20')


@dataclass(frozen=True)
class ReferenceTerm:
    __canonical_type_id__ = 'sentinel.reference_term'
    __canonical_type_version__ = '1'
    name: str
    value: float
    signed_components: tuple[tuple[str, float], ...]

    def __post_init__(self):
        _number(self.value)
        if not self.name or not math.isfinite(self.value):
            raise ValueError('finite named term required')
        if not isinstance(self.signed_components, tuple) or any(not math.isfinite(v) for _, v in self.signed_components):
            raise ValueError('immutable finite components required')


@dataclass(frozen=True)
class ReferenceCoverage:
    __canonical_type_id__ = 'sentinel.reference_coverage'
    __canonical_type_version__ = '1'
    required: int
    usable: int
    prior_usable: tuple[tuple[str, int], ...]

    def __post_init__(self):
        if type(self.required) is not int or type(self.usable) is not int:
            raise TypeError('integer support counts required')
        if not 0 <= self.usable <= self.required or any(type(n) is not int or not 0 <= n <= 252 for _, n in self.prior_usable):
            raise ValueError('invalid support counts')
        if not isinstance(self.prior_usable, tuple):
            raise TypeError('immutable support counts required')


@dataclass(frozen=True)
class CompositeReference:
    __canonical_type_id__ = 'sentinel.composite_reference'
    __canonical_type_version__ = '1'
    schema_version: str
    reference_config_id: str
    snapshot_id: str
    decision_cutoff: datetime
    data_status: DataStatus
    value: float | None
    delta: float | None
    group_contributions: tuple[ReferenceTerm, ...]
    input_measurement_ids: tuple[str, ...]
    coverage: ReferenceCoverage
    qualifiers: tuple[str, ...]
    reference_id: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'decision_cutoff', utc(self.decision_cutoff))
        if self.reference_config_id not in (PRESSURE, DIVERGENCE) or not isinstance(self.data_status, DataStatus):
            raise ValueError('frozen typed reference configuration required')
        if not isinstance(self.coverage, ReferenceCoverage):
            raise TypeError('typed coverage required')
        for name in ('group_contributions', 'input_measurement_ids', 'qualifiers'):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError('immutable reference required')
        if any(not isinstance(t, ReferenceTerm) for t in self.group_contributions):
            raise TypeError('typed contribution required')
        if not self.snapshot_id or self.schema_version != 'sentinel-composite-reference-v1':
            raise ValueError('versioned snapshot reference required')
        if self.value is not None:
            _number(self.value)
        if self.delta is not None:
            _number(self.delta)
        if self.data_status is DataStatus.AVAILABLE:
            if self.value is None or not math.isfinite(self.value) or self.coverage.usable != self.coverage.required:
                raise ValueError('AVAILABLE requires finite complete value')
            expected_names = tuple(g[0] for g in GROUPS) if self.reference_config_id == PRESSURE else PAIRS
            if tuple(t.name for t in self.group_contributions) != expected_names:
                raise ValueError('named frozen contribution groups required')
            expected = sum(t.value for t in self.group_contributions) if self.reference_config_id == PRESSURE else max((t.value for t in self.group_contributions), default=float('nan'))
            if not math.isclose(self.value, expected, abs_tol=1e-10, rel_tol=0):
                raise ValueError('contribution mismatch')
            if self.reference_config_id == PRESSURE and not 0 <= self.value <= 100:
                raise ValueError('pressure outside percentile range')
        elif self.value is not None or self.delta is not None or self.group_contributions:
            raise ValueError('unavailable reference must have null values and no aggregate terms')
        if self.delta is not None and not math.isfinite(self.delta):
            raise ValueError('finite delta required')
        object.__setattr__(self, 'input_measurement_ids', tuple(sorted(set(self.input_measurement_ids))))
        object.__setattr__(self, 'qualifiers', tuple(sorted(set(self.qualifiers))))
        fields = {k: v for k, v in vars(self).items() if k != 'reference_id'}
        object.__setattr__(self, 'reference_id', stable_content_hash(fields))


class ReferenceBuilder:
    def __init__(self, calendar: SessionCalendar):
        self.calendar = calendar

    def _check(self, state: StateBuild):
        snap = state.snapshot
        if snap.protocol_digest != FROZEN_PROTOCOL_DIGEST or snap.calendar_version != self.calendar.calendar_version:
            raise ValueError('reference requires frozen matching protocol/calendar')
        if snap.vintage_mode is not VintageMode.RECORDED_AS_AVAILABLE:
            raise ValueError('descriptive latest vintage prohibited in causal reference')
        if self.calendar.get(snap.session_id).decision_cutoff != snap.decision_cutoff:
            raise ValueError('original snapshot cutoff required')

    def _usable(self, state: StateBuild, sensor: str) -> bool:
        m = state.measurement(sensor)
        # Only current-session measurements at their ORIGINAL snapshot cutoff.
        return m.data_status is DataStatus.AVAILABLE and 'LAGGED_INPUT' not in m.qualifiers

    def build(self, current: StateBuild, history: tuple[StateBuild, ...]) -> tuple[CompositeReference, ...]:
        if not isinstance(history, tuple):
            raise TypeError('immutable recorded snapshot history required')
        self._check(current)
        previous_days = {s.session_id for s in self.calendar.history(current.snapshot.session_id, 254)[:-1]}
        prior = {}
        for state in history:
            if state.snapshot.session_id not in previous_days:
                continue  # Future snapshots cannot alter an earlier result.
            self._check(state)
            sid = state.snapshot.session_id
            if sid in prior and prior[sid] != state:
                raise ValueError('conflicting recorded snapshots for one decision')
            prior[sid] = state
        ordered = tuple(prior[k] for k in sorted(prior))
        result = []
        for config in (PRESSURE, DIVERGENCE):
            current_days = {s.session_id for s in self.calendar.history(current.snapshot.session_id, 253)[:-1]}
            ref = self._compute(current, tuple(s for s in ordered if s.snapshot.session_id in current_days), config)
            preceding = self.calendar.history(current.snapshot.session_id, 2)
            if len(preceding) == 2 and preceding[0].session_id in prior and ref.data_status is DataStatus.AVAILABLE:
                old_state = prior[preceding[0].session_id]
                old_days = {s.session_id for s in self.calendar.history(old_state.snapshot.session_id, 253)[:-1]}
                old = self._compute(old_state, tuple(s for s in ordered if s.snapshot.session_id in old_days), config)
                if old.data_status is DataStatus.AVAILABLE:
                    from dataclasses import replace
                    ref = replace(ref, delta=ref.value-old.value, input_measurement_ids=ref.input_measurement_ids+old.input_measurement_ids)
            result.append(ref)
        return tuple(result)

    def _compute(self, current, history, config):
        sensors = tuple(s for _, members, _ in GROUPS for s, _ in members) if config == PRESSURE else PAIRS
        statuses, transformed, counts, ids = [], {}, [], []
        for sensor in sensors:
            m = current.measurement(sensor)
            ids.append(m.measurement_id)
            past = []
            for state in history:
                old = state.measurement(sensor)
                if old.descriptor_version != m.descriptor_version:
                    raise ValueError('source/method binding changed within reference window')
                if self._usable(state, sensor):
                    past.append(old.value)
                    ids.append(old.measurement_id)
            counts.append((sensor, len(past)))
            if m.data_status is not DataStatus.AVAILABLE:
                statuses.append(m.data_status)
            elif not self._usable(current, sensor):
                statuses.append(DataStatus.STALE)
            elif len(past) < 126:
                statuses.append(DataStatus.INSUFFICIENT_HISTORY)
            elif config == PRESSURE:
                transformed[sensor] = (sum(x < m.value for x in past)+.5*sum(x == m.value for x in past))/len(past)
                statuses.append(DataStatus.AVAILABLE)
            else:
                center = median(past)
                mad = median(abs(x-center) for x in past)
                if mad == 0:
                    statuses.append(DataStatus.INSUFFICIENT_HISTORY)
                else:
                    transformed[sensor] = (m.value-center)/(1.4826*mad)
                    statuses.append(DataStatus.AVAILABLE)
        status = aggregate_status(tuple(statuses))
        terms, value = (), None
        if status is DataStatus.AVAILABLE:
            if config == PRESSURE:
                terms = tuple(ReferenceTerm(name, 100/3*sum(w*(1-transformed[s] if inverse else transformed[s]) for s,w in members),
                              tuple((s, 1-transformed[s] if inverse else transformed[s]) for s,_ in members)) for name,members,inverse in GROUPS)
                value = sum(t.value for t in terms)
            else:
                terms = tuple(ReferenceTerm(s, abs(transformed[s]), ((s, transformed[s]),)) for s in sensors)
                value = max(t.value for t in terms)
        return CompositeReference('sentinel-composite-reference-v1', config, current.snapshot.snapshot_id,
                 current.snapshot.decision_cutoff, status, value, None, terms, tuple(ids),
                 ReferenceCoverage(len(sensors), statuses.count(DataStatus.AVAILABLE), tuple(counts)),
                 ('RESEARCH_ONLY','NOT_A_FORECAST','NOT_PRIORITY', 'LIMITED_US_EQUITY_PRESSURE' if config == PRESSURE else 'DIVERGENCE_NOT_BEARISH',
                  'REF-ECB-CISS-2012' if config == PRESSURE else 'REF-NIST-ROBUST-Z','REF-SENTINEL-G-V1'))
