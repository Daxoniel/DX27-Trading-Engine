"""Task 6B-2F: frozen-winner diagnostics, never model selection or production."""

import argparse
import csv
from dataclasses import asdict, replace
from datetime import date
from fractions import Fraction
import hashlib
import io
import json
from math import isclose
from pathlib import Path
from statistics import median
import subprocess

import pandas as pd

from dx27.intelligence.sentinel.research.trend_metrics import (
    DateSplit, SPLITS, directional_transitions, evaluate_metrics,
    match_transitions, persistence_lengths, state_agreement,
)
from dx27.intelligence.sentinel.research.trend_models import candidate_series
from dx27.intelligence.sentinel.research.trend_tournament import (
    REQUIRED_COLUMNS, STAGE_A_SYMBOLS, read_csv, validate_dataframe,
)

WINNER = 'ewmac_64_256'
NEIGHBOURS = ('ewmac_32_128', 'ewmac_16_64')
METRICS = ('false_reversal_rate_10', 'false_reversal_rate_20',
           'directional_consistency_20', 'directional_consistency_60',
           'mfe_60_median', 'mae_60_median')
REGIMES = tuple(DateSplit(name, date.fromisoformat(start), date.fromisoformat(end)) for name, start, end in (
    ('pre_gfc_expansion', '2005-01-01', '2007-10-08'),
    ('global_financial_crisis', '2007-10-09', '2009-03-09'),
    ('post_gfc_bull_qe', '2009-03-10', '2015-12-31'),
    ('late_cycle_pre_covid', '2016-01-01', '2019-12-31'),
    ('covid_shock_recovery', '2020-01-01', '2020-12-31'),
    ('post_covid_risk_on', '2021-01-01', '2021-12-31'),
    ('inflation_rate_shock', '2022-01-01', '2022-12-31'),
    ('current_post_2022', '2023-01-01', '2026-09-30'),
))
FULL = DateSplit('full', date(2005, 1, 1), date(2026, 9, 30))
WINDOWS = (FULL, *SPLITS)
GROUPS = {'broad_equity': ('SPY', 'QQQ', 'IWM'),
          'equity_sectors': ('XLK', 'XLF', 'XLE', 'XLV', 'XLI', 'XLP', 'XLY', 'XLU'),
          'rates': ('TLT',), 'gold': ('GLD',)}
PROTOCOL = {
    'protocol_id': 'dx27.trend.robustness.v0.1', 'frozen_winner': WINNER,
    'regimes': [asdict(r) for r in REGIMES], 'asset_groups': GROUPS,
    'observation_delays': [0, 1, 2, 3],
    'aggregation': 'Rates pooled from integer eligible/event counts; MFE/MAE pooled event medians; duration pooled directional-run median. Also report unweighted symbol medians.',
    'major_regime_valid_transitions': 'At least 20 transitions with complete 60 observed-bar forward windows within that regime, pooled across the fixed 13 ETFs.',
    'decision_scope': 'Regime pooled event rates; full-period per-symbol rates; full-period pooled baseline minus delay-3 directional_consistency_60.',
    'event_windows': 'Existing evaluate_metrics semantics, clipped at the relevant scope end; no crossing regime/split ends. Audit includes full-period and regime-clipped outcomes.',
    'delay_semantics': 'Original observation at i-delay is attached to current daily bar i; unavailable prefix stays None. Prices and date axis never move.',
    'neighbour_matching': 'Existing ascending-A nearest-unused-B +/-3 observed-bar matching; A is lexical first candidate, earlier B breaks ties; absolute timing differences in observed trading bars, matched events only.',
    'missing_values': 'Undefined remains null; no imputation; unavailable required decision rates prevent PASS. Regimes below 20 valid transitions are descriptive only.',
    'fail': {'regime_false_reversal_20_above': .50, 'regime_directional_60_below': .40,
             'delay3_directional_60_deterioration_above': .15,
             'symbols_directional_60_below_040_more_than': 3, 'integrity_failure': True},
    'pass': {'regime_false_reversal_20_at_most': .35, 'regime_directional_60_at_least': .45,
             'delay3_directional_60_deterioration_at_most': .10,
             'symbols_directional_60_at_least_045_minimum': 10},
}


class IntegrityError(ValueError):
    """Frozen source or reproducible research result differs from Stage-A."""


def json_text(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False,
                      default=lambda v: v.isoformat() if isinstance(v, date) else v) + '\n'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def context():
    root = Path(__file__).resolve().parents[2]
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip():
        raise IntegrityError('Clean execution tree required')
    return root, subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def verify_stage_a(source, root):
    hashes = json.loads((source / 'trend_stage_a_artifact_hashes.json').read_text())
    for name, expected in hashes.items():
        if sha(source / name) != expected:
            raise IntegrityError('Stage-A artifact hash mismatch: ' + name)
    manifest = json.loads((source / 'trend_stage_a_data_manifest.json').read_text())
    lock = json.loads((source / 'trend_stage_a_selection_lock.json').read_text())
    report = json.loads((source / 'trend_stage_a_report.json').read_text())
    if lock['provisional_selection_winner'] != WINNER or report['selection_winner'] != WINNER or report['final_verdict'] != 'STAGE_A_WEAK_PASS':
        raise IntegrityError('Unexpected frozen winner or Stage-A verdict')
    combined = sha(source / 'stage_a_adjusted_daily.csv')
    if any(x['combined_dataset_sha256'] != combined for x in (manifest, lock, report)):
        raise IntegrityError('Frozen combined data hash mismatch')
    if sha(source / 'trend_stage_a_selection_ranking.csv') != lock['selection_ranking_sha256'] or sha(source / 'trend_stage_a_selection_lock.json') != report['selection_lock_sha256']:
        raise IntegrityError('Stage-A lock/ranking hash mismatch')
    # Verify the actual implementations used in Stage-A, not a branch name.
    for name in ('trend_models.py', 'trend_metrics.py', 'trend_tournament.py', 'trend_selection.py'):
        path = 'src/dx27/intelligence/sentinel/research/' + name
        original = subprocess.check_output(['git', 'show', manifest['execution_commit'] + ':' + path], cwd=root)
        if original != (root / path).read_bytes():
            raise IntegrityError('Frozen implementation changed: ' + name)
    lines = (source / 'stage_a_adjusted_daily.csv').read_bytes().splitlines(keepends=True)
    for symbol, info in manifest['per_symbol_metadata'].items():
        blob = lines[0] + b''.join(line for line in lines[1:] if line.split(b',', 1)[0] == symbol.encode())
        if hashlib.sha256(blob).hexdigest() != info['sha256']:
            raise IntegrityError('Frozen symbol hash mismatch: ' + symbol)
    return manifest, hashes


def delay_observations(observations, delay):
    if delay not in (0, 1, 2, 3):
        raise ValueError('Only fixed observation delays 0..3 are allowed')
    result = []
    for i, current in enumerate(observations):
        original = observations[i-delay] if i >= delay else None
        result.append(replace(current, state=original.state if original else None,
                              primary_value=original.primary_value if original else None,
                              normalized_score=original.normalized_score if original else None,
                              sigma_daily=original.sigma_daily if original else None,
                              rsi_14=original.rsi_14 if original else None,
                              diagnostics=original.diagnostics if original else {},
                              is_ready=original.is_ready if original else False))
    return tuple(result)


def event_audit(observations, closes, split):
    states = tuple(o.state for o in observations)
    selected = {i for i, o in enumerate(observations) if split.start <= o.date <= split.end}
    available = [i for i in sorted(selected) if states[i] is not None]
    positions = {i: p for p, i in enumerate(available)}
    output = []
    for i in directional_transitions(states):
        if i not in selected:
            continue
        row = dict(symbol=observations[i].symbol, transition_date=observations[i].date.isoformat(),
                   previous_state=states[i-1].name, new_state=states[i].name,
                   regime=next(r.name for r in REGIMES if r.start <= observations[i].date <= r.end))
        for n in (10, 20):
            future = available[positions[i]+1:positions[i]+n+1]
            row['false_reversal_' + str(n)] = any(states[j] == states[i-1] for j in future) if len(future) == n else None
        for n in (20, 60):
            eligible = i+n in selected
            row['directional_consistency_' + str(n)] = int(states[i]) * (closes[i+n]/closes[i]-1) > 0 if eligible else None
            if n == 60:
                returns = [int(states[i]) * (closes[j]/closes[i]-1) for j in range(i+1, i+n+1)] if eligible else []
                row['mfe_60'] = max(returns) if returns else None
                row['mae_60'] = min(returns) if returns else None
        output.append(row)
    return output


def scope_metrics(observations, closes, split):
    values = dict(evaluate_metrics(observations, closes, split).values)
    events = event_audit(observations, closes, split)
    if len(events) != values['transitions']:
        raise IntegrityError('Transition audit count differs from existing evaluator')
    for event_field, metric, eligible in (
        ('false_reversal_10', 'false_reversal_rate_10', 'eligible_false_reversal_10'),
        ('false_reversal_20', 'false_reversal_rate_20', 'eligible_false_reversal_20'),
        ('directional_consistency_20', 'directional_consistency_20', 'eligible_directional_20'),
        ('directional_consistency_60', 'directional_consistency_60', 'eligible_directional_60'),
    ):
        outcomes = [e[event_field] for e in events if e[event_field] is not None]
        count = sum(outcomes)
        if len(outcomes) != values[eligible] or (outcomes and not isclose(count / len(outcomes), values[metric], rel_tol=1e-12, abs_tol=1e-12)):
            raise IntegrityError('Event outcome disagrees with frozen evaluator: ' + metric)
        values[event_field + '_count'] = count
    for field in ('mfe_60', 'mae_60'):
        samples = [e[field] for e in events if e[field] is not None]
        if samples and not isclose(median(samples), values[field + '_median'], rel_tol=1e-12, abs_tol=1e-12):
            raise IntegrityError('Excursion audit differs from existing evaluator')
    runs = persistence_lengths([o.state for o in observations if split.start <= o.date <= split.end])
    values.update(scope=split.name, symbol=observations[0].symbol,
                  valid_transitions=values['eligible_directional_60'],
                  median_state_duration=values['persistence_median'])
    return values, events, runs


def pooled(rows, events, runs, label):
    result = dict(label=label, symbols=len(rows), transition_count=sum(r['transitions'] for r in rows),
                  valid_transitions=sum(r['valid_transitions'] for r in rows),
                  median_state_duration=median(runs) if runs else None)
    for metric, field in (('false_reversal_rate_10', 'false_reversal_10'),
                          ('false_reversal_rate_20', 'false_reversal_20'),
                          ('directional_consistency_20', 'directional_consistency_20'),
                          ('directional_consistency_60', 'directional_consistency_60')):
        outcomes = [e[field] for e in events if e[field] is not None]
        result[metric] = sum(outcomes)/len(outcomes) if outcomes else None
        result[field + '_eligible'] = len(outcomes)
        result[field + '_count'] = sum(outcomes)
    for field in ('mfe_60', 'mae_60'):
        values = [e[field] for e in events if e[field] is not None]
        result[field + '_median'] = median(values) if values else None
    for metric in METRICS:
        values = [r[metric] for r in rows if r[metric] is not None]
        result[metric + '_symbol_median'] = median(values) if values else None
    return result


def dispersion(rows):
    result = {}
    for metric in (*METRICS, 'transitions', 'median_state_duration', 'false_reversal_10_count', 'false_reversal_20_count'):
        present = [r for r in rows if r[metric] is not None]
        values = pd.Series([r[metric] for r in present], dtype='float64')
        lower_better = metric.startswith('false_reversal')
        if present:
            ordered = sorted(present, key=lambda r: (r[metric] if lower_better else -r[metric], r['symbol']))
            extrema = dict(best_symbol=ordered[0]['symbol'], best_value=ordered[0][metric],
                           worst_symbol=ordered[-1]['symbol'], worst_value=ordered[-1][metric])
        else:
            extrema = dict(best_symbol=None, best_value=None, worst_symbol=None, worst_value=None)
        result[metric] = dict(median=float(values.median()) if len(values) else None,
                             p25=float(values.quantile(.25)) if len(values) else None,
                             p75=float(values.quantile(.75)) if len(values) else None,
                             defined_symbols=len(present), **extrema,
                             extrema_interpretation='numeric maximum/minimum, no desirability score' if metric in ('transitions', 'median_state_duration') else 'metric direction only')
    return result


def compare(left, right, split):
    # Keep lexical pairing orientation exactly as the existing sensitivity code.
    if left[0].candidate_id > right[0].candidate_id:
        left, right = right, left
    indices = [i for i, o in enumerate(left) if split.start <= o.date <= split.end]
    selected = set(indices)
    a, b = [o.state for o in left], [o.state for o in right]
    common, agreement = state_agreement([a[i] for i in indices], [b[i] for i in indices])
    ta = [i for i in directional_transitions(a) if i in selected]
    tb = [i for i in directional_transitions(b) if i in selected]
    paired = match_transitions(ta, tb)
    denominator = len(ta) + len(tb) - len(paired)
    return dict(scope=split.name, symbol=left[0].symbol, candidate_a=left[0].candidate_id,
                candidate_b=right[0].candidate_id, common_evaluated_dates=common,
                state_agreement=agreement, disagreement_rate=1-agreement if agreement is not None else None,
                transitions_a=len(ta), transitions_b=len(tb), matched_transitions=len(paired),
                transition_jaccard_3=len(paired)/denominator if denominator else None,
                matched_absolute_timing_differences=';'.join(str(abs(a-b)) for a, b in paired),
                median_absolute_transition_timing_difference=median([abs(a-b) for a, b in paired]) if paired else None)


def decide(regimes, symbols, timing, integrity_ok=True):
    major = [r for r in regimes if r['valid_transitions'] >= 20]
    fail, missing = [], []
    for r in major:
        fr, dc = r['false_reversal_rate_20'], r['directional_consistency_60']
        if fr is None or dc is None:
            missing.append(r['label'])
        if fr is not None and fr > .50:
            fail.append(r['label'] + ': false_reversal_rate_20 > 0.50')
        if dc is not None and dc < .40:
            fail.append(r['label'] + ': directional_consistency_60 < 0.40')
    baseline, delayed = (timing[d]['directional_consistency_60'] for d in (0, 3))
    def exact_rate(row):
        count, eligible = row.get('directional_consistency_60_count'), row.get('directional_consistency_60_eligible')
        return Fraction(count, eligible) if eligible else Fraction(str(row['directional_consistency_60']))
    exact_deterioration = exact_rate(timing[0])-exact_rate(timing[3]) if baseline is not None and delayed is not None else None
    deterioration = float(exact_deterioration) if exact_deterioration is not None else None
    if deterioration is None:
        missing.append('delay3 comparison undefined')
    elif exact_deterioration > Fraction(15, 100):
        fail.append('+3-day directional deterioration > 0.15')
    below = [r['symbol'] for r in symbols if r['directional_consistency_60'] is not None and r['directional_consistency_60'] < .40]
    good = [r['symbol'] for r in symbols if r['directional_consistency_60'] is not None and r['directional_consistency_60'] >= .45]
    if len(below) > 3:
        fail.append('More than three ETFs have directional_consistency_60 < 0.40')
    if not integrity_ok:
        fail.append('Reproducible implementation/data integrity failure')
    passed = (not fail and not missing and len(good) >= 10 and exact_deterioration is not None and exact_deterioration <= Fraction(10, 100)
              and all(r['false_reversal_rate_20'] <= .35 and r['directional_consistency_60'] >= .45 for r in major))
    return dict(verdict='ROBUSTNESS_FAIL' if fail else 'ROBUSTNESS_PASS' if passed else 'ROBUSTNESS_CONDITIONAL',
                fail_conditions=fail, undefined_conditions=missing, major_regimes=[r['label'] for r in major],
                descriptive_only_regimes=[r['label'] for r in regimes if r['valid_transitions'] < 20],
                delay3_directional_60_deterioration=deterioration,
                symbols_below_040=below, symbols_at_least_045=good)


def write_csv(rows, path):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def write_json(value, path):
    with path.open('x', encoding='utf-8', newline='') as handle:
        handle.write(json_text(value))


def verify_saved_results(source, series, closes):
    # Reproduce frozen metrics/sensitivity, without calling any selector.
    saved = pd.read_csv(source / 'tournament/trend_metrics.csv', keep_default_na=False)
    sensitivity = pd.read_csv(source / 'tournament/trend_sensitivity.csv', keep_default_na=False)
    for symbol in STAGE_A_SYMBOLS:
        for split in SPLITS:
            current = evaluate_metrics(series[symbol][WINNER], closes[symbol], split).values
            previous = saved[(saved.symbol == symbol) & (saved.split == split.name) & (saved.candidate_id == WINNER)].iloc[0]
            for key, value in current.items():
                old = previous[key]
                if (value is None and old != '') or (value is not None and (old == '' or not isclose(float(old), value, rel_tol=1e-12, abs_tol=1e-12))):
                    raise IntegrityError('Stage-A metric reproduction failed: ' + symbol + '/' + key)
            for neighbour in NEIGHBOURS:
                current = compare(series[symbol][WINNER], series[symbol][neighbour], split)
                previous = sensitivity[(sensitivity.symbol == symbol) & (sensitivity.split == split.name)
                                       & (sensitivity.candidate_a == neighbour) & (sensitivity.candidate_b == WINNER)].iloc[0]
                for key in ('common_evaluated_dates', 'state_agreement', 'transitions_a', 'transitions_b', 'transition_jaccard_3'):
                    old, value = previous[key], current[key]
                    if (value is None and old != '') or (value is not None and (old == '' or not isclose(float(old), value, rel_tol=1e-12, abs_tol=1e-12))):
                        raise IntegrityError('Stage-A sensitivity reproduction failed: ' + symbol + '/' + key)
    # Verify all three diagnostic state sequences against the frozen state file.
    expected = {(s, c, o.date.isoformat()): o.state.name if o.state is not None else ''
                for s, configs in series.items() for c, observations in configs.items() for o in observations}
    seen = set()
    with (source / 'tournament/trend_states.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row['candidate_id'] not in (WINNER, *NEIGHBOURS):
                continue
            key = row['symbol'], row['candidate_id'], row['date']
            if key in seen or key not in expected or expected[key] != row['state']:
                raise IntegrityError('Frozen diagnostic state mismatch')
            seen.add(key)
    if seen != set(expected):
        raise IntegrityError('Incomplete frozen diagnostic state coverage')


def markdown(report):
    def table(rows, columns):
        def fmt(v):
            return 'undefined' if v is None else f'{v:.6f}' if isinstance(v, float) else str(v)
        return '\n'.join(['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join('---' for _ in columns) + ' |',
                          *['| ' + ' | '.join(fmt(row.get(k)) for k in columns) + ' |' for row in rows]])
    columns = ['label', 'transition_count', 'valid_transitions', *METRICS, 'median_state_duration']
    lines = ['# Task 6B-2F frozen-winner robustness', '',
             'Winner: ewmac_64_256. Stage-A remains STAGE_A_WEAK_PASS.',
             'Execution commit: ' + report['execution_commit'],
             'Dataset SHA256: ' + report['combined_dataset_sha256'],
             'Protocol SHA256: ' + report['protocol_sha256'], '',
             '## Fixed evaluation semantics', '', PROTOCOL['aggregation'],
             PROTOCOL['major_regime_valid_transitions'], PROTOCOL['event_windows'], '',
             '## Regimes', '', table(report['regimes'], columns), '',
             '## Asset groups (full period)', '', table([r for r in report['asset_groups'] if r['scope'] == 'full'], columns), '',
             '## Symbols (full period)', '', table([dict(label=r['symbol'], transition_count=r['transitions'], **r) for r in report['symbols'] if r['scope'] == 'full'], columns), '',
             '## Timing perturbation (full period)', '', table([r for r in report['timing'] if r['scope'] == 'full'], columns + ['state_agreement', 'transition_jaccard_3']), '',
             '## Cross-symbol dispersion', '', table([dict(metric=k, **v) for k, v in report['symbol_dispersion']['full'].items()], ['metric', 'median', 'p25', 'p75', 'best_symbol', 'worst_symbol']), '',
             '## Transition audit', '', json_text(report['event_summary']), '',
             '## Neighbour diagnostic: unweighted symbol medians', '',
             table(report['neighbour_aggregate'], ['scope', 'neighbour', 'state_agreement', 'transition_jaccard_3', 'median_absolute_transition_timing_difference', 'disagreement_rate']), '',
             'Matching timing difference is conditional on +/-3-bar matches; unmatched transitions are not assigned a fabricated lag.', '',
             '## Decision', '', json_text(report['decision']), report['final_verdict'],
             'frozen_winner = ewmac_64_256', 'winner_reselected = false', 'stage_a_result_changed = false',
             'production_trend_detector_created = false', '']
    return '\n'.join(lines)


def run(source, destination):
    root, commit = context()
    if destination == root or root in destination.parents or source == destination or source in destination.parents:
        raise ValueError('New output directory must be outside Git and frozen Stage-A')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('New empty destination required')
    destination.mkdir(parents=True, exist_ok=True)
    # Persist all decisions before loading any per-regime metric or state result.
    write_json(dict(**PROTOCOL, execution_commit=commit), destination / 'trend_robustness_protocol.json')
    protocol_hash = sha(destination / 'trend_robustness_protocol.json')
    manifest, original_hashes = verify_stage_a(source, root)
    bars = validate_dataframe(read_csv(source / 'stage_a_adjusted_daily.csv'))
    if set(b.symbol for b in bars) != set(STAGE_A_SYMBOLS):
        raise IntegrityError('Exactly 13 frozen ETFs required')
    series, closes = {}, {}
    for symbol in STAGE_A_SYMBOLS:
        selected = [b for b in bars if b.symbol == symbol]
        closes[symbol] = tuple(b.close for b in selected)
        calculated = candidate_series(symbol, tuple(b.date for b in selected), closes[symbol])
        series[symbol] = {c: tuple(o for o in calculated if o.candidate_id == c) for c in (WINNER, *NEIGHBOURS)}
    verify_saved_results(source, series, closes)
    scopes, events, runs = {}, {}, {}
    for split in (*WINDOWS, *REGIMES):
        scopes[split.name], events[split.name], runs[split.name] = [], [], []
        for symbol in STAGE_A_SYMBOLS:
            row, event, duration = scope_metrics(series[symbol][WINNER], closes[symbol], split)
            scopes[split.name].append(row)
            events[split.name].extend(event)
            runs[split.name].extend(duration)
    regimes = [dict(start=r.start.isoformat(), end=r.end.isoformat(),
                    **pooled(scopes[r.name], events[r.name], runs[r.name], r.name)) for r in REGIMES]
    groups = []
    for split in WINDOWS:
        for group, symbols in GROUPS.items():
            local_runs = [n for s in symbols for n in persistence_lengths([o.state for o in series[s][WINNER] if split.start <= o.date <= split.end])]
            groups.append(dict(scope=split.name, members=';'.join(symbols),
                               **pooled([r for r in scopes[split.name] if r['symbol'] in symbols],
                                        [e for e in events[split.name] if e['symbol'] in symbols], local_runs, group)))
    timing, timing_symbols = [], []
    for split in WINDOWS:
        for delay in (0, 1, 2, 3):
            local_rows, local_events, local_runs, comparisons = [], [], [], []
            for symbol in STAGE_A_SYMBOLS:
                baseline = series[symbol][WINNER]
                delayed = delay_observations(baseline, delay)
                row, event, duration = scope_metrics(delayed, closes[symbol], split)
                comparison = compare(baseline, delayed, split)
                comparison.update(delay=delay)
                timing_symbols.append(dict(**row, delay=delay, state_agreement=comparison['state_agreement'],
                                           transition_jaccard_3=comparison['transition_jaccard_3']))
                local_rows.append(row); local_events.extend(event); local_runs.extend(duration); comparisons.append(comparison)
            value = pooled(local_rows, local_events, local_runs, 'delay_' + str(delay))
            common = sum(c['common_evaluated_dates'] for c in comparisons)
            denominator = sum(c['transitions_a'] + c['transitions_b'] - c['matched_transitions'] for c in comparisons)
            value.update(scope=split.name, delay=delay,
                         state_agreement=sum(c['state_agreement']*c['common_evaluated_dates'] for c in comparisons if c['common_evaluated_dates'])/common if common else None,
                         transition_jaccard_3=sum(c['matched_transitions'] for c in comparisons)/denominator if denominator else None)
            timing.append(value)
    neighbours = [dict(neighbour=c, **compare(series[s][WINNER], series[s][c], split))
                  for split in (*WINDOWS, *REGIMES) for c in NEIGHBOURS for s in STAGE_A_SYMBOLS]
    neighbour_aggregate = []
    for split in (*WINDOWS, *REGIMES):
        for candidate in NEIGHBOURS:
            subset = [r for r in neighbours if r['scope'] == split.name and r['neighbour'] == candidate]
            value = dict(scope=split.name, neighbour=candidate, symbols=len(subset),
                         matched_transitions=sum(r['matched_transitions'] for r in subset),
                         transitions_a=sum(r['transitions_a'] for r in subset), transitions_b=sum(r['transitions_b'] for r in subset))
            for key in ('state_agreement', 'transition_jaccard_3', 'median_absolute_transition_timing_difference', 'disagreement_rate'):
                samples = [r[key] for r in subset if r[key] is not None]
                value[key] = median(samples) if samples else None
            differences = [int(v) for r in subset for v in r['matched_absolute_timing_differences'].split(';') if v]
            value['pooled_matched_transition_timing_median'] = median(differences) if differences else None
            neighbour_aggregate.append(value)
    regime_events = {(e['symbol'], e['transition_date']): e for r in REGIMES for e in events[r.name]}
    audit = []
    for event in events['full']:
        row = dict(event)
        local = regime_events[event['symbol'], event['transition_date']]
        row.update({'regime_' + k: local[k] for k in ('false_reversal_10', 'false_reversal_20', 'directional_consistency_20', 'directional_consistency_60', 'mfe_60', 'mae_60')})
        audit.append(row)
    full_timing = {r['delay']: r for r in timing if r['scope'] == 'full'}
    decision = decide(regimes, scopes['full'], full_timing)
    if context()[1] != commit or sha(destination / 'trend_robustness_protocol.json') != protocol_hash:
        raise IntegrityError('Execution context/protocol changed')
    verify_stage_a(source, root)
    symbols = [r for split in WINDOWS for r in scopes[split.name]]
    report = dict(execution_commit=commit, stage_a_execution_commit=manifest['execution_commit'],
                  combined_dataset_sha256=manifest['combined_dataset_sha256'], protocol_sha256=protocol_hash,
                  protocol=PROTOCOL, stage_a_artifact_hashes=original_hashes, source_integrity_verified=True,
                  frozen_metric_and_state_reproduction_verified=True, frozen_winner=WINNER,
                  winner_reselected=False, stage_a_result_changed=False, stage_a_result='STAGE_A_WEAK_PASS',
                  production_trend_detector_created=False, regimes=regimes, asset_groups=groups,
                  symbols=symbols, symbol_dispersion={split.name: dispersion(scopes[split.name]) for split in WINDOWS},
                  timing=timing, timing_symbol_diagnostics=timing_symbols, neighbour_diagnostics=neighbours,
                  neighbour_aggregate=neighbour_aggregate, decision=decision, final_verdict=decision['verdict'],
                  event_summary=dict(total=len(audit), by_regime={r.name:len(events[r.name]) for r in REGIMES},
                                     by_symbol={s:sum(e['symbol']==s for e in audit) for s in STAGE_A_SYMBOLS},
                                     full_period_eligible_60=sum(e['directional_consistency_60'] is not None for e in audit),
                                     regime_clipped_eligible_60=sum(e['regime_directional_consistency_60'] is not None for e in audit)),
                  equity_dominance=dict(equity_symbols=11, total_symbols=13,
                                        equal_symbol_weight_share=11/13,
                                        equity_transition_share=sum(e['symbol'] not in ('TLT','GLD') for e in audit)/len(audit) if audit else None,
                                        note='Stage-A medians have 11/13 equity constituents; pooled event shares are descriptive, never performance-tuned weights.'),
                  limitations=['Short regimes censor forward windows; insufficient-transition regimes are diagnostic only.',
                               'Neighbour timing differences cover +/-3-bar matched events only; low matching coverage precludes interpreting them as global lag.',
                               'Regimes are retrospectively date-defined stress segments, not prospective regime labels.',
                               'No production detector is built regardless of verdict.'])
    write_csv(regimes, destination / 'trend_robustness_regimes.csv')
    write_csv(symbols, destination / 'trend_robustness_symbols.csv')
    write_csv(timing, destination / 'trend_robustness_timing.csv')
    write_csv(audit, destination / 'trend_transition_events.csv')
    write_csv(groups, destination / 'trend_robustness_asset_groups.csv')
    write_csv(neighbours, destination / 'trend_robustness_neighbours.csv')
    write_json(report, destination / 'trend_robustness_report.json')
    with (destination / 'trend_robustness_summary.md').open('x', encoding='utf-8') as handle:
        handle.write(markdown(report))
    write_json({p.name:sha(p) for p in sorted(destination.iterdir()) if p.is_file()}, destination / 'trend_robustness_artifact_hashes.json')
    print(decision['verdict'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-a-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.stage_a_dir.resolve(), args.output_dir.resolve())
    except IntegrityError as exc:
        # Integrity failure is an explicit frozen FAIL condition, never a new winner.
        print('ROBUSTNESS_FAIL: reproducible integrity failure:', str(exc))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
