"""Project state evidence into MarketNow v0.2 slots, not a full report engine."""

from dx27.intelligence.sentinel.market_state import StateBuild
from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.sensor_contracts import VintageMode


def project_market_now(build: StateBuild) -> dict:
    """Return a plain report projection without holdings, priority or Analyst input.

    Values are typed unit-bearing objects inside the existing StateValue pattern.
    Unavailable values are null. Partial sector members are explicitly separate
    context, never a completed vector or rank. No composite/forecast is populated.
    """
    descriptors = {d.sensor_id: d for d in build.descriptors}
    points = {p.point_id: p for p in build.input_points}

    def entry(measurement):
        descriptor = descriptors[measurement.sensor_id]
        qualifiers = set(measurement.qualifiers)
        if descriptor.proxy_for:
            qualifiers.add('PROXY_FOR:' + descriptor.proxy_for)
        if descriptor.dimension == 'participation':
            qualifiers.add('TRUE_BREADTH_UNAVAILABLE')
        if measurement.data_status is not DataStatus.AVAILABLE:
            value = None
        elif isinstance(measurement.value, tuple):
            value = {'unit': measurement.unit, 'members': [
                {'subject_id': v.subject_id, 'value': v.value} for v in measurement.value]}
        else:
            value = {'unit': measurement.unit, 'amount': measurement.value}
        source_refs = sorted({(points[i].source_id, points[i].source_record_id, points[i].source_version)
                              for i in measurement.input_point_ids})
        return {'sensor_id': measurement.sensor_id, 'measurement_ref': measurement.measurement_id,
                'state': {'value': value, 'state_as_of': measurement.observation_window.end.isoformat(),
                          'data_status': measurement.data_status.value,
                          'source_refs': [{'source_id': s, 'source_record_id': r, 'source_version': v} for s, r, v in source_refs],
                          'evidence_refs': list(measurement.input_point_ids),
                          'method_id': measurement.method_id + ':' + measurement.method_version,
                          'qualifiers': sorted(qualifiers)}}

    def dimension(name):
        return [entry(m) for m in build.measurements if descriptors[m.sensor_id].dimension == name]

    coverage = build.snapshot.coverage
    current = {
        'status': 'COMPLETE' if coverage.grade == 'COMPLETE' else 'DEGRADED' if coverage.grade == 'PARTIAL' else 'UNAVAILABLE',
        'as_of': build.snapshot.decision_cutoff.isoformat(),
        'broad_equity': dimension('trend'),
        'leadership': [e for e in dimension('leadership') if e['sensor_id'] != 'sector_relative_20'] + [entry(m) for m in build.sector_context],
        'participation': dimension('participation'),
        'volatility': dimension('volatility'), 'rates': dimension('rates'), 'credit': dimension('credit'),
        'usd_and_macro_series': [],
        'major_relationships': [entry(m) for m in build.measurements if m.measurement_id in build.snapshot.relationships],
        'active_structural_conditions': dimension('funding'),
        'source_event_ids': [],
        'coverage': {'grade': coverage.grade,
            'registered': {'expected': coverage.registered.expected, 'available': coverage.registered.available},
            'active_required': {'expected': coverage.active_required.expected, 'available': coverage.active_required.available},
            'optional': {'expected': coverage.optional.expected, 'available': coverage.optional.available},
            'blocked': {'expected': coverage.blocked.expected, 'available': coverage.blocked.available},
            'qualifiers': ['TRUE_BREADTH_UNAVAILABLE', 'CONCENTRATION_UNAVAILABLE', 'USD_MACRO_NOT_IMPLEMENTED'] +
                          (['DESCRIPTIVE_ONLY'] if build.snapshot.vintage_mode is VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY else [])},
        'state_snapshot_ref': {'snapshot_id': build.snapshot.snapshot_id, 'schema_version': build.snapshot.schema_version,
                               'protocol_digest': build.snapshot.protocol_digest},
        'reference_values': [], 'conditional_forecasts': [],
    }
    return {'report_schema_version': 'sentinel-report-multisensor-v0.2', 'market_now': current}
