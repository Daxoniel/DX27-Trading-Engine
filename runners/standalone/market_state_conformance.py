"""Run frozen 6B-2H synthetic conformance, not a live-market effectiveness test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from dx27.intelligence.sentinel.identity import canonical_json, stable_content_hash
from dx27.intelligence.sentinel.market_state import FROZEN_PROTOCOL_DIGEST
from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.research.sensor_protocol import load_protocol, verify_protocol_lock
from dx27.intelligence.sentinel.research.state_fixture import synthetic_state_fixture
from dx27.intelligence.sentinel.state_projection import project_market_now


def run(protocol_dir: Path, output: Path) -> dict:
    verify_protocol_lock(protocol_dir / 'protocol.json', protocol_dir / 'protocol_lock.json')
    fixture = synthetic_state_fixture(load_protocol(protocol_dir / 'protocol.json'))
    registry, calendar, bindings, points, builder, returns, prices = fixture
    sessions = calendar.sessions[20:45]
    snapshots = []
    formula_errors = []
    prefix_mismatches = causal_violations = imputation_violations = proxy_violations = 0
    availability = {f.feed_id: 0 for f in registry.feeds if f.feed_id in {'spy', 'rsp', 'qqq', 'iwm', 'vix', 'hy_oas', 'ust_2y', 'ust_10y'}}
    for i, session in enumerate(sessions, start=20):
        state = builder.build(session.session_id, points)
        prefix = tuple(p for p in points if p.available_at <= session.decision_cutoff and p.observation_window.end <= session.decision_cutoff)
        replay = builder.build(session.session_id, prefix)
        prefix_mismatches += state != replay
        snapshots.append(state.snapshot.snapshot_id)
        raw = np.asarray(returns['spy'][i-19:i+1])
        expected = {
            'spy_return_20': float(np.sum(raw)),
            'rsp_return_20': float(np.sum(returns['rsp'][i-19:i+1])),
            'qqq_spy_relative_20': float(np.sum(returns['qqq'][i-19:i+1]) - np.sum(raw)),
            'iwm_spy_relative_20': float(np.sum(returns['iwm'][i-19:i+1]) - np.sum(raw)),
            'rsp_spy_relative_20': float(np.sum(returns['rsp'][i-19:i+1]) - np.sum(raw)),
            'spy_rv_20': float(np.std(raw, ddof=1)*np.sqrt(252)*100),
            'spy_rv_5_over_20': float(np.std(raw[-5:], ddof=1)/np.std(raw, ddof=1)),
            'vix_level': 18.0,
            'vix_minus_rv_20': float(18.0-np.std(raw, ddof=1)*np.sqrt(252)*100),
            'hy_oas_level': 320.0,
            'ust_2y_level': 2.5, 'ust_10y_level': 4.0,
            'ust_10y_minus_2y': 150.0, 'sofr_minus_effr': 10.0,
        }
        for sensor, value in expected.items():
            actual = state.measurement(sensor)
            if actual.data_status is not DataStatus.AVAILABLE:
                raise ValueError('complete fixture unexpectedly unavailable: '+sensor)
            formula_errors.append(abs(actual.value-value))
        for entry in state.measurement('sector_relative_20').value:
            feed = entry.subject_id.split(':',1)[1]
            formula_errors.append(abs(entry.value-(float(np.sum(returns[feed][i-19:i+1]))-expected['spy_return_20'])))
        for point in state.input_points:
            causal_violations += point.available_at > session.decision_cutoff or point.observation_window.end > session.decision_cutoff
        for measurement in state.measurements:
            imputation_violations += measurement.data_status is not DataStatus.AVAILABLE and measurement.value is not None
        part = next(d for d in state.snapshot.dimensions if d.dimension_id == 'participation')
        proxy_violations += 'PROXY_ONLY' not in part.qualifiers or 'TRUE_BREADTH_UNAVAILABLE' not in part.qualifiers
        used = {p.subject_ref.subject_id for p in state.input_points if p.data_status is DataStatus.AVAILABLE and p.observation_window.end == session.closes_at}
        for feed in availability:
            availability[feed] += 'fixture:'+feed in used
    metrics = {'maximum_absolute_formula_error': max(formula_errors), 'formula_comparisons': len(formula_errors),
               'prefix_replay_mismatches': prefix_mismatches, 'causal_violations': causal_violations,
               'missing_or_stale_as_zero_violations': imputation_violations, 'proxy_as_authoritative_violations': proxy_violations}
    passed = max(formula_errors) <= 1e-10 and not any((prefix_mismatches,causal_violations,imputation_violations,proxy_violations))
    if not passed:
        raise ValueError('state conformance failed: '+json.dumps(metrics))
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    report = {
        'task_id': '6B-2H', 'result': 'IMPLEMENTATION_CONFORMANCE_PASS', 'data_role': 'SYNTHETIC_FIXTURE_ONLY',
        'runtime_commit': revision, 'protocol_digest': FROZEN_PROTOCOL_DIGEST,
        'calendar_version': calendar.calendar_version, 'calendar_bounds': [calendar.valid_from,calendar.valid_through],
        'fixture_dataset_sha256': stable_content_hash(points), 'fixture_bindings_sha256': stable_content_hash(bindings),
        'decision_sessions': len(sessions), 'first_decision_session': sessions[0].session_id,
        'last_decision_session': sessions[-1].session_id, 'metrics': metrics,
        'fixture_required_feed_coverage': {f: n/len(sessions) for f,n in availability.items()},
        'live_operational_gate': {'result': 'BLOCKED_DATA', 'real_provider_bindings_verified': False,
                                 'real_observation_sessions': 0, 'coverage': None, 'minimum_coverage': 0.95},
        'market_effectiveness_validated': False, 'composites_enabled': False, 'detectors_enabled': False,
        'forecasts_enabled': False, 'snapshot_ids': snapshots,
    }
    sample = builder.build(sessions[-1].session_id,points)
    output.mkdir(parents=True,exist_ok=True)
    (output/'state_conformance_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (output/'market_now_sample.json').write_text(json.dumps(project_market_now(sample),indent=2,allow_nan=False)+'\n')
    (output/'state_evidence_sample.json').write_text(canonical_json(sample)+'\n')
    (output/'fixture_bindings.json').write_text(canonical_json(bindings)+'\n')
    artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob('*.json'))
                 if p.name != 'artifact_hashes.json'}
    (output/'artifact_hashes.json').write_text(json.dumps(artifacts,indent=2)+'\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol-dir',type=Path,default=Path(__file__).resolve().parents[2]/'research/sentinel/6b-2g-contracts')
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    report = run(args.protocol_dir,args.output_dir)
    print(json.dumps({'task_id': report['task_id'], 'result': report['result'], 'metrics': report['metrics'],
                      'live_operational_gate': report['live_operational_gate']},sort_keys=True))


if __name__=='__main__':
    main()
