"""Pre-result checks of fixed stress boundaries, event audit and decision gates."""
from dataclasses import replace
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import json
from math import sin

import pandas as pd
import pytest

from dx27.intelligence.sentinel.research.trend_metrics import DateSplit
from dx27.intelligence.sentinel.research.trend_models import TrendObservation, TrendState

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('robustness', ROOT / 'runners/standalone/trend_robustness.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def observations(states):
    return tuple(TrendObservation('SPY', date(2020, 1, 1)+timedelta(days=i), r.WINNER, 'ewmac',
                                  state, float(i), float(i), .1, 50., state is not None,
                                  'QC_RESEARCH_REPRODUCTION', False) for i, state in enumerate(states))


def fixtures():
    regimes = [dict(label='regime', valid_transitions=20, false_reversal_rate_20=.35,
                    directional_consistency_60=.45)]
    symbols = [dict(symbol=s, directional_consistency_60=.45) for s in r.STAGE_A_SYMBOLS]
    timing = {0:dict(directional_consistency_60=.5), 3:dict(directional_consistency_60=.4)}
    return regimes, symbols, timing


def test_date_regimes_partition_full_period_without_gaps():
    assert r.REGIMES[0].start == r.FULL.start
    assert r.REGIMES[-1].end == r.FULL.end
    assert all(a.end+timedelta(days=1) == b.start for a, b in zip(r.REGIMES, r.REGIMES[1:]))
    assert len(r.REGIMES) == 8
    assert sorted(s for group in r.GROUPS.values() for s in group) == sorted(r.STAGE_A_SYMBOLS)


@pytest.mark.parametrize('delay', [0, 1, 2, 3])
def test_delays_use_only_available_past_observation_and_preserve_dates(delay):
    states = [TrendState.BULLISH]*8 + [TrendState.BEARISH]*8
    original = observations(states)
    delayed = r.delay_observations(original, delay)
    assert [o.date for o in delayed] == [o.date for o in original]
    for i, o in enumerate(delayed):
        assert o.state == (original[i-delay].state if i >= delay else None)
        assert o.primary_value == (original[i-delay].primary_value if i >= delay else None)
    modified_future = original[:7] + tuple(replace(o, state=TrendState.NEUTRAL) for o in original[7:])
    assert r.delay_observations(modified_future, delay)[:7] == delayed[:7]


def test_event_audit_keeps_bad_events_and_matches_frozen_metrics():
    states = [TrendState.BULLISH]*5 + [TrendState.BEARISH]*3 + [None]*2 + [TrendState.BULLISH]*100
    obs = observations(states)
    closes = tuple(100+i for i in range(len(states)))
    split = DateSplit('test', obs[0].date, obs[-1].date)
    metrics, events, _ = r.scope_metrics(obs, closes, split)
    assert len(events) == 1  # None interrupts the direct directional reversal.
    assert events[0]['false_reversal_10'] is True
    assert events[0]['false_reversal_20'] is True
    assert events[0]['directional_consistency_60'] is False
    assert metrics['false_reversal_20_count'] == 1
    assert events[0]['mae_60'] < 0


def test_regime_boundary_transition_retained_and_future_censored():
    obs = observations([TrendState.BULLISH]*3 + [TrendState.BEARISH]*100)
    closes = tuple(100+i for i in range(len(obs)))
    split = DateSplit('short', obs[3].date, obs[12].date)
    metrics, events, _ = r.scope_metrics(obs, closes, split)
    assert metrics['transitions'] == 1
    assert metrics['valid_transitions'] == 0
    assert events[0]['false_reversal_10'] is None
    assert events[0]['directional_consistency_60'] is None
    assert events[0]['mfe_60'] is None


def test_timing_jaccard_pairs_original_shifted_events():
    obs = observations([TrendState.BULLISH]*10+[TrendState.BEARISH]*10+[TrendState.BULLISH]*100)
    comparison = r.compare(obs, r.delay_observations(obs, 3), r.FULL)
    assert comparison['transition_jaccard_3'] == 1
    assert comparison['median_absolute_transition_timing_difference'] == 3


def test_no_transition_means_undefined_rates_not_zero():
    obs = observations([TrendState.BULLISH]*100)
    metrics, events, runs = r.scope_metrics(obs, [100]*100, r.FULL)
    assert events == [] and metrics['directional_consistency_60'] is None
    pooled = r.pooled([metrics], events, runs, 'constant')
    assert pooled['false_reversal_rate_20'] is None
    assert pooled['median_state_duration'] == 100


@pytest.mark.parametrize('failure', ['false_reversal', 'direction', 'delay', 'four_symbols', 'integrity'])
def test_each_frozen_fail_gate_independently(failure):
    regimes, symbols, timing = fixtures()
    if failure == 'false_reversal': regimes[0]['false_reversal_rate_20'] = .50001
    if failure == 'direction': regimes[0]['directional_consistency_60'] = .39999
    if failure == 'delay': timing[3]['directional_consistency_60'] = .34999
    if failure == 'four_symbols':
        for row in symbols[:4]: row['directional_consistency_60'] = .39999
    result = r.decide(regimes, symbols, timing, integrity_ok=failure != 'integrity')
    assert result['verdict'] == 'ROBUSTNESS_FAIL'
    assert len(result['fail_conditions']) == 1


def test_pass_exact_thresholds_and_three_bad_symbols():
    regimes, symbols, timing = fixtures()
    for row in symbols[:3]: row['directional_consistency_60'] = .39
    assert r.decide(regimes, symbols, timing)['verdict'] == 'ROBUSTNESS_PASS'


@pytest.mark.parametrize('condition', ['reversal', 'direction', 'delay', 'symbols'])
def test_conditional_without_any_fail_gate(condition):
    regimes, symbols, timing = fixtures()
    if condition == 'reversal': regimes[0]['false_reversal_rate_20'] = .50
    if condition == 'direction': regimes[0]['directional_consistency_60'] = .40
    if condition == 'delay': timing[3]['directional_consistency_60'] = .35  # Exactly .15: not FAIL.
    if condition == 'symbols':
        for row in symbols[:4]: row['directional_consistency_60'] = .44
    result = r.decide(regimes, symbols, timing)
    assert result['verdict'] == 'ROBUSTNESS_CONDITIONAL'
    assert result['fail_conditions'] == []


def test_small_regime_diagnostic_only_and_missing_rates_not_imputed():
    regimes, symbols, timing = fixtures()
    regimes.append(dict(label='small', valid_transitions=19, false_reversal_rate_20=.9,
                        directional_consistency_60=.1))
    assert r.decide(regimes, symbols, timing)['verdict'] == 'ROBUSTNESS_PASS'
    timing[3]['directional_consistency_60'] = None
    result = r.decide(regimes, symbols, timing)
    assert result['verdict'] == 'ROBUSTNESS_CONDITIONAL'
    assert result['delay3_directional_60_deterioration'] is None


def test_timing_deterioration_uses_exact_event_counts():
    regimes, symbols, timing = fixtures()
    timing[0] = dict(directional_consistency_60=.5, directional_consistency_60_count=10, directional_consistency_60_eligible=20)
    timing[3] = dict(directional_consistency_60=.35, directional_consistency_60_count=7, directional_consistency_60_eligible=20)
    result = r.decide(regimes, symbols, timing)
    assert result['verdict'] == 'ROBUSTNESS_CONDITIONAL'
    assert result['delay3_directional_60_deterioration'] == .15


def test_pooled_rates_use_fixed_eligible_counts_and_excursion_event_medians():
    a = observations([TrendState.BULLISH]*2+[TrendState.BEARISH]*80)
    b = observations([TrendState.BULLISH]*10+[TrendState.BEARISH]*10+[TrendState.BULLISH]*80)
    rows, events, runs = [], [], []
    for obs in (a, b):
        row, event, run = r.scope_metrics(obs, tuple(100+i for i in range(len(obs))), r.FULL)
        rows.append(row); events.extend(event); runs.extend(run)
    pooled = r.pooled(rows, events, runs, 'fixture')
    assert pooled['directional_consistency_60'] == 1/3
    assert pooled['false_reversal_rate_20'] == 1/3
    assert pooled['valid_transitions'] == 3


def test_protocol_serialization_deterministic_and_no_selector_import():
    assert r.json_text(r.PROTOCOL) == r.json_text(r.PROTOCOL)
    source = (ROOT / 'runners/standalone/trend_robustness.py').read_text()
    assert 'select_trend(' not in source
    assert 'run_tournament(' not in source


def test_mutated_stage_a_artifact_is_integrity_failure(tmp_path):
    (tmp_path / 'data.csv').write_text('original')
    (tmp_path / 'trend_stage_a_artifact_hashes.json').write_text(json.dumps({'data.csv':r.sha(tmp_path/'data.csv')}))
    (tmp_path / 'data.csv').write_text('changed')
    with pytest.raises(r.IntegrityError, match='hash mismatch'):
        r.verify_stage_a(tmp_path, ROOT)


def test_synthetic_end_to_end_deterministic_and_stage_a_untouched(monkeypatch, tmp_path):
    dates = pd.bdate_range('2003-01-02', periods=256).strftime('%Y-%m-%d').tolist()
    dates += pd.bdate_range('2005-01-03', periods=350).strftime('%Y-%m-%d').tolist()
    dates += pd.bdate_range('2020-01-02', periods=180).strftime('%Y-%m-%d').tolist()
    dates += ['2026-09-30']
    records = []
    for symbol in r.STAGE_A_SYMBOLS:
        for i, day in enumerate(dates):
            close = 100+10*sin(i/35)
            records.append(dict(symbol=symbol, date=day, open=close, high=close+1, low=close-1, close=close, volume=100))
    source = tmp_path / 'stage_a'
    source.mkdir()
    pd.DataFrame(records).to_csv(source/'stage_a_adjusted_daily.csv', index=False)
    before = (source/'stage_a_adjusted_daily.csv').read_bytes()
    manifest = dict(execution_commit='a'*40, combined_dataset_sha256=r.sha(source/'stage_a_adjusted_daily.csv'))
    monkeypatch.setattr(r, 'context', lambda: (ROOT, 'b'*40))
    monkeypatch.setattr(r, 'verify_stage_a', lambda *args: (manifest, {'stage_a_adjusted_daily.csv':manifest['combined_dataset_sha256']}))
    monkeypatch.setattr(r, 'verify_saved_results', lambda *args: None)
    outputs = []
    for name in ('first', 'second'):
        output = tmp_path / name
        report = r.run(source, output)
        assert report['winner_reselected'] is False
        assert report['stage_a_result_changed'] is False
        assert report['production_trend_detector_created'] is False
        assert len(report['symbols']) == 39
        assert len(report['regimes']) == 8
        assert len(report['timing']) == 12
        assert len(report['neighbour_diagnostics']) == 286
        hashes = json.loads((output/'trend_robustness_artifact_hashes.json').read_text())
        assert all(r.sha(output/k) == v for k, v in hashes.items())
        event_frame = pd.read_csv(output/'trend_transition_events.csv')
        assert len(event_frame) == report['event_summary']['total']
        outputs.append({p.name:p.read_bytes() for p in output.iterdir()})
    assert outputs[0] == outputs[1]
    assert (source/'stage_a_adjusted_daily.csv').read_bytes() == before
    with pytest.raises(ValueError, match='empty'):
        r.run(source, tmp_path/'first')
