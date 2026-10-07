"""Regression checks for unsafe mutations of the pre-registered design artifact."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.research.sensor_protocol import (
    load_protocol, validate_protocol, verify_protocol_lock,
)

PROTOCOL_DIR = Path(__file__).resolve().parents[2] / 'research/sentinel/6b-2g-contracts'


@pytest.fixture
def protocol():
    return load_protocol(PROTOCOL_DIR / 'protocol.json')


def test_frozen_registry_is_valid_and_not_runtime_approval():
    report = verify_protocol_lock(PROTOCOL_DIR / 'protocol.json', PROTOCOL_DIR / 'protocol_lock.json')
    assert report['result'] == 'PROTOCOL_VALID'
    assert report['runtime_validated'] is False
    assert report['market_effectiveness_validated'] is False


@pytest.mark.parametrize(('path', 'unsafe'), [
    (('availability', 'fill_missing_sessions'), True),
    (('availability', 'historical_latest_vintage_role'), 'CAUSAL_CONFIRMATION'),
    (('availability', 'unknown_publication'), 'ASSUME_DATE_CLOSE'),
    (('availability', 'revision_replay_policy'), 'OVERWRITE_PRIOR_SNAPSHOTS'),
    (('availability', 'maximum_reference_source_age_sessions'), 1),
    (('evaluation', 'development_audit_start'), '2019-01-01'),
    (('availability', 'eligibility'), 'observation_time<=decision_cutoff'),
    (('availability', 'history_must_be_available_at_cutoff'), False),
    (('availability', 'non_available_value_policy'), 'ZERO'),
    (('availability', 'missing_weight_policy'), 'RENORMALIZE_AVAILABLE'),
    (('availability', 'decision_calendar'), 'WEEKDAYS_ONLY'),
    (('availability', 'consecutive_return_sessions_required'), False),
    (('dimension_policy', 'proxy_counts_as_constituent_breadth'), True),
    (('dimension_policy', 'global_regime_labels'), True),
    (('reference_research', 'runtime_enabled'), True),
    (('reference_research', 'combines_pressure_and_divergence'), True),
    (('reference_research', 'percentile', 'include_current'), True),
    (('reference_research', 'groups', 'equity_weakness', 'direction'), 'PERCENTILE'),
    (('evaluation', 'labels_evaluation_only'), False),
    (('evaluation', 'confirmation'), 'REUSE_2020_2026_AS_UNTOUCHED'),
    (('evaluation', 'purge_sessions'), 10),
    (('evaluation', 'matching', 'one_to_one'), False),
    (('evaluation', 'matching', 'window_sessions'), [-5, 5]),
    (('evaluation', 'matching', 'availability_exclusions'), 'DROP_UNAVAILABLE'),
    (('evaluation', 'bootstrap', 'rematch_at_block_joins'), True),
    (('evaluation', 'unavailable_required_metric_policy'), 'PASS'),
    (('evaluation', 'forecast_gate', 'runtime_enabled'), True),
    (('evaluation', 'change_gate', 'pooled_results_cannot_override_failed_stratum'), False),
    (('report_revision', 'priority_from_composite'), True),
    (('report_revision', 'market_state_independent_of_portfolio'), False),
    (('implementation_gate', 'ewmac_production_approved'), True),
])
def test_unsafe_protocol_changes_are_rejected(protocol, path, unsafe):
    changed = deepcopy(protocol)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = unsafe
    with pytest.raises(ValueError):
        validate_protocol(changed)


def test_proxy_and_pit_features_cannot_be_silently_promoted(protocol):
    proxy = next(s for s in protocol['sensors'] if s['sensor_id'] == 'rsp_spy_relative_20')
    proxy['evidence_role'] = 'DIRECT'
    with pytest.raises(ValueError, match='proxy'):
        validate_protocol(protocol)
    proxy['evidence_role'] = 'PROXY'
    pit = next(s for s in protocol['sensors'] if s['sensor_id'] == 'constituent_breadth_20')
    pit['input_feed_ids'] = ['rsp']
    with pytest.raises(ValueError, match='PIT'):
        validate_protocol(protocol)


@pytest.mark.parametrize('mutation', ['unknown_feed', 'duplicate_id', 'unknown_method', 'wrong_unit', 'bad_weight', 'nan'])
def test_corrupt_registry_and_nonfinite_scores_are_rejected(protocol, mutation):
    if mutation == 'unknown_feed':
        protocol['sensors'][0]['input_feed_ids'] = ['SPX_FAKE']
    elif mutation == 'duplicate_id':
        protocol['feeds'].append(deepcopy(protocol['feeds'][0]))
    elif mutation == 'unknown_method':
        protocol['sensors'][0]['method_id'] = 'future_aware_trend'
    elif mutation == 'wrong_unit':
        protocol['sensors'][0]['unit'] = 'basis_points'
    elif mutation == 'bad_weight':
        protocol['reference_research']['groups']['credit']['weight'] = 0.9
    else:
        protocol['reference_research']['groups']['credit']['weight'] = float('nan')
    with pytest.raises(ValueError):
        validate_protocol(protocol)


def test_future_label_followup_and_forecast_status_remain_explicit(protocol):
    protocol['evaluation']['targets']['trend_shift']['horizon_sessions'] = 20
    with pytest.raises(ValueError, match='followup'):
        validate_protocol(protocol)


def test_lock_rejects_even_semantically_safe_unregistered_change(protocol, tmp_path):
    protocol['evaluation']['change_gate']['minimum_precision'] = 0.61
    path = tmp_path / 'protocol.json'
    path.write_text(json.dumps(protocol))
    validate_protocol(protocol)
    with pytest.raises(ValueError, match='raw protocol lock mismatch'):
        verify_protocol_lock(path, PROTOCOL_DIR / 'protocol_lock.json')


def test_lock_checks_canonical_digest_independently(protocol, tmp_path):
    path = tmp_path / 'protocol.json'
    path.write_text(json.dumps(protocol))
    lock = {'protocol_id': protocol['protocol_id'], 'version': protocol['version'],
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'canonical_sha256': '0' * 64}
    lock_path = tmp_path / 'lock.json'
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match='canonical protocol lock mismatch'):
        verify_protocol_lock(path, lock_path)
    lock['canonical_sha256'] = stable_content_hash(protocol)
    lock_path.write_text(json.dumps(lock))
    assert verify_protocol_lock(path, lock_path)['result'] == 'PROTOCOL_VALID'


def test_duplicate_json_keys_cannot_override_a_frozen_policy(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"fill_missing_sessions":false,"fill_missing_sessions":true}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        load_protocol(path)
