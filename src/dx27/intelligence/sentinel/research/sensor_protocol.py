"""Offline checks for the frozen multi-sensor design, not runtime measurement."""

from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import DataStatus


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite_tree(value: Any) -> None:
    if isinstance(value, float):
        _require(math.isfinite(value), "protocol numbers must be finite")
    elif isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)


def _unique(items: list[dict], key: str) -> dict[str, dict]:
    ids = [item[key] for item in items]
    _require(all(isinstance(i, str) and i.strip() for i in ids), f"invalid {key}")
    _require(len(ids) == len(set(ids)), f"duplicate {key}")
    return dict(zip(ids, items))


def validate_protocol(protocol: dict) -> None:
    """Check design safety and internal references without running any sensors.

    Exact artifact equality is checked separately by ``verify_protocol_lock``;
    these checks explain important invalid mutations rather than replace a lock.
    """
    _finite_tree(protocol)
    _require(protocol['task_id'] == '6B-2G', 'wrong task')
    _require(protocol['status'] == 'FROZEN_DESIGN_NOT_RUNTIME_IMPLEMENTATION',
             'protocol must not claim runtime implementation')
    feeds = _unique(protocol['feeds'], 'feed_id')
    sensors = _unique(protocol['sensors'], 'sensor_id')
    methods = protocol['methods']
    dims = set(protocol['dimension_policy']['dimensions'])
    _require(len(dims) == 7, 'seven dimensions required')
    for feed in feeds.values():
        _require(feed['historical_vintage_required'] is True, 'vintage evidence required')
        expected_age = 0 if feed['kind'] == 'ETF' else 1
        _require(feed['max_age_sessions'] == expected_age, 'incorrect source freshness')
        _require(feed['normalized_unit'] in {'USD', 'percent_annualized',
                 'basis_points', 'percent_per_annum'}, 'unknown feed unit')
    for sensor in sensors.values():
        _require(sensor['method_id'] in methods, 'unregistered method')
        _require(sensor['dimension'] in dims, 'unregistered dimension')
        _require(set(sensor['input_feed_ids']) <= feeds.keys(), 'unknown input feed')
        unit = methods[sensor['method_id']]['output_unit']
        if unit == 'SAME_AS_INPUT':
            _require(len(sensor['input_feed_ids']) == 1, 'scalar identity method needs one feed')
            unit = feeds[sensor['input_feed_ids'][0]]['normalized_unit']
        _require(sensor['unit'] == unit, 'method unit mismatch')
        _require(sensor['evidence_role'] in {'DIRECT', 'PROXY'}, 'unknown evidence role')
        _require(type(sensor['lookback_sessions']) is int and
                 sensor['lookback_sessions'] >= 0, 'invalid lookback')
        if sensor['activation'] == 'BLOCKED_PIT_INPUTS':
            _require(not sensor['input_feed_ids'] and not sensor['required_for_dimension'],
                     'blocked PIT sensor cannot be silently activated')
        else:
            _require(sensor['activation'] in {'ACTIVE_CONTRACT', 'OPTIONAL_CONTRACT'}
                     and bool(sensor['input_feed_ids']), 'invalid active sensor')
    for sid in ['rsp_return_20', 'qqq_spy_relative_20', 'iwm_spy_relative_20',
                'rsp_spy_relative_20', 'vix_minus_rv_20', 'sector_relative_20']:
        _require(sensors[sid]['evidence_role'] == 'PROXY', 'proxy cannot become authoritative')
    dp = protocol['dimension_policy']
    _require(dp['proxy_counts_as_constituent_breadth'] is False, 'proxy is not breadth')
    _require(dp['global_regime_labels'] is False, 'global regime not approved')
    avail = protocol['availability']
    _require(avail['eligibility'] == 'max(published_at,first_seen_at)<=decision_cutoff',
             'both publication and capture must precede cutoff')
    _require(avail['history_must_be_available_at_cutoff'] is True and
             avail['observation_must_be_completed'] is True, 'causal history required')
    _require(avail['fill_missing_sessions'] is False and
             avail['non_available_value_policy'] == 'NULL' and
             avail['missing_weight_policy'] == 'UNAVAILABLE_NO_REWEIGHT',
             'missing values cannot be imputed or reweighted')
    _require(avail['consecutive_return_sessions_required'] is True, 'no compressed sessions')
    _require(avail['decision_calendar'] == 'XNYS_VERSIONED' and
             avail['decision_offset_minutes_after_actual_close'] == 120,
             'actual session close and versioned calendar required')
    _require(avail['failure_precedence'] == ['SOURCE_ERROR', 'UNSUPPORTED_SESSION',
             'UNAVAILABLE', 'STALE', 'INSUFFICIENT_HISTORY', 'AVAILABLE'] and
             set(avail['failure_precedence']) == {s.value for s in DataStatus},
             'reuse existing DataStatus values in frozen precedence')
    _require(avail['historical_latest_vintage_role'] == 'DESCRIPTIVE_ONLY_NOT_CAUSAL_CONFIRMATION',
             'latest vintage cannot certify historical causal availability')
    _require(avail['unknown_publication'] == 'use_first_seen_at_only_no_backdating' and
             avail['revision_replay_policy'] == 'append_only_do_not_rewrite_emitted_snapshots',
             'no invented availability or rewritten history')
    _require(avail['maximum_reference_source_age_sessions'] == 0, 'references cannot use lagged levels')
    contracts = protocol['contracts']
    for name, contract in contracts.items():
        fields = contract['fields']
        _require(len(fields) == len(set(fields)), f'duplicate fields in {name}')
    _require({'published_at', 'first_seen_at', 'available_at', 'revision_id', 'vintage_mode'}
             <= set(contracts['SeriesPoint']['fields']), 'series needs temporal vintage fields')
    _require('qualifiers' in contracts['ConditionalForecast']['fields'], 'disabled forecast reasons required')
    ref = protocol['reference_research']
    _require(ref['runtime_enabled'] is False, 'references await validation')
    _require(ref['combines_pressure_and_divergence'] is False, 'S and D must be separate')
    _require(ref['missing_weight_policy'] == 'UNAVAILABLE_NO_REWEIGHT', 'no hidden reweighting')
    groups = ref['groups']
    _require(math.isclose(sum(g['weight'] for g in groups.values()), 1, abs_tol=1e-12),
             'group weights must sum to one')
    for group in groups.values():
        _require(group['weight'] > 0, 'group weights must be positive')
        _require(set(group['members']) <= sensors.keys(), 'unknown reference sensor')
        _require(all(w > 0 for w in group['members'].values()) and
                 math.isclose(sum(group['members'].values()), 1, abs_tol=1e-12),
                 'within-group weights must be positive and sum to one')
    _require(groups['equity_weakness']['direction'] == 'INVERSE_PERCENTILE',
             'rising returns are not equity pressure')
    _require(groups['volatility']['direction'] == groups['credit']['direction'] == 'PERCENTILE',
             'volatility and credit orientation invalid')
    _require(ref['percentile']['include_current'] is False, 'exclude current from normalization')
    _require(0 < ref['percentile']['minimum_usable_points'] <= ref['percentile']['window_sessions'],
             'invalid reference support')
    _require(set(ref['relationship_members']) <= sensors.keys(), 'unknown relationship member')
    evaluation = protocol['evaluation']
    _require(evaluation['labels_evaluation_only'] is True, 'future labels cannot become features')
    _require(evaluation['confirmation'] == 'PROSPECTIVE_ONLY_AFTER_CANDIDATE_FREEZE',
             'observed history is not fresh confirmation')
    start, end = map(date.fromisoformat, evaluation['development_period'])
    selection_end = date.fromisoformat(evaluation['development_selection_end'])
    audit_start = date.fromisoformat(evaluation['development_audit_start'])
    _require(start <= selection_end < audit_start <= end, 'development split overlap')
    _require(evaluation['development_role'] == 'PREVIOUSLY_OBSERVED_NOT_FRESH_HOLDOUT',
             'observed development is not untouched data')
    horizons = []
    for target in evaluation['targets'].values():
        _require(sum(target['future_blocks_sessions']) == target['horizon_sessions'],
                 'target followup mismatch')
        _require(target['refractory_sessions'] == target['horizon_sessions'],
                 'target deduplication must match followup')
        _require(target['event_type'] in {'TREND_CHANGE', 'VOLATILITY_CHANGE', 'RELATIONSHIP_CHANGE'},
                 'unapproved change target')
        horizons.append(target['horizon_sessions'])
    _require(evaluation['purge_sessions'] >= max(horizons) and
             evaluation['embargo_sessions'] >= max(horizons), 'split leakage protection too short')
    _require(evaluation['matching']['one_to_one'] is True and
             evaluation['matching']['window_sessions'] == [0, 5], 'no retroactive or reused matching')
    _require(evaluation['matching']['availability_exclusions'] ==
             'count_as_abstentions_not_dropped_from_miss_denominator', 'abstention cannot hide misses')
    _require(evaluation['unavailable_required_metric_policy'] == 'NO_PASS', 'undefined cannot pass')
    _require(evaluation['forecast_gate']['runtime_enabled'] is False and
             evaluation['reference_gate']['runtime_enabled'] is False, 'future outputs not approved')
    _require(evaluation['bootstrap']['rematch_at_block_joins'] is False, 'no invented bootstrap chronology')
    gate = evaluation['change_gate']
    _require(gate['minimum_labels_per_target_subject_direction'] >= 30 and
             gate['pooled_results_cannot_override_failed_stratum'] is True,
             'sparse or failed strata cannot be pooled into promotion')
    _require(0 < gate['minimum_precision'] <= 1 and 0 < gate['minimum_recall'] <= 1 and
             0 < gate['minimum_evaluation_availability'] <= 1, 'invalid metric bounds')
    report = protocol['report_revision']
    _require(report['priority_from_composite'] is False and
             report['p0_and_top_k_rules_changed'] is False, 'priority boundary cannot change')
    _require(report['conditional_forecasts_default'] == [], 'forecasts disabled by default')
    _require(report['market_state_independent_of_portfolio'] is True, 'global state independent of holdings')
    _require(protocol['implementation_gate']['ewmac_production_approved'] is False,
             'archived EWMAC cannot be promoted by contract revision')


def _unique_keys(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_protocol(path: Path) -> dict:
    return json.loads(path.read_text(), object_pairs_hook=_unique_keys)


def verify_protocol_lock(path: Path, lock_path: Path) -> dict:
    protocol = load_protocol(path)
    validate_protocol(protocol)
    lock = load_protocol(lock_path)
    _require(lock['protocol_id'] == protocol['protocol_id'] and
             lock['version'] == protocol['version'], 'lock identity mismatch')
    _require(lock['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest(), 'raw protocol lock mismatch')
    _require(lock['canonical_sha256'] == stable_content_hash(protocol), 'canonical protocol lock mismatch')
    return {'task_id': protocol['task_id'], 'result': 'PROTOCOL_VALID',
            'runtime_validated': False, 'market_effectiveness_validated': False,
            'protocol_digest': lock['canonical_sha256'],
            'feed_count': len(protocol['feeds']), 'sensor_count': len(protocol['sensors'])}
