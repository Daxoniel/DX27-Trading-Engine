"""Freeze Yahoo Stage-A input, lock selection, then validate OOS without tuning."""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess

import numpy
import pandas as pd
import yfinance

# Same-directory standalone loader; no frozen research implementation changes.
import trend_stage_a_yahoo as yahoo
from dx27.intelligence.sentinel.research.trend_selection import (
    PROTOCOL_ID, ELIGIBLE_IDS, EXCLUDED_IDS, METRIC_DIRECTIONS,
    select_trend, selection_report_json, selection_ranking_csv,
)
from dx27.intelligence.sentinel.research.trend_tournament import read_csv, run_tournament, write_outputs


class StageARunError(ValueError):
    """Execution or freeze invariant failed; no Stage-A verdict is available."""


def execution_context():
    root = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    if git('status', '--porcelain'):
        raise StageARunError('Clean working tree required before Yahoo acquisition')
    return dict(execution_commit=git('rev-parse', 'HEAD'), python_version=platform.python_version(),
                yfinance_version=yfinance.__version__, pandas_version=pd.__version__, numpy_version=numpy.__version__)


def canonical_csv(frame):
    handle = io.StringIO(newline='')
    frame.loc[:, list(yahoo.REQUIRED_COLUMNS)].sort_values(['symbol', 'date']).to_csv(
        handle, index=False, lineterminator='\n')
    return handle.getvalue().encode('utf-8')


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def assert_frozen(path, expected):
    if digest(path.read_bytes()) != expected:
        raise StageARunError('Frozen dataset or selection lock changed; aborting')


def save_json(value, path):
    contents = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'
    # Exclusive creation establishes a logical immutable freeze/lock. Never
    # overwrite a previous experiment or silently resume after partial failure.
    with path.open('x', encoding='utf-8', newline='') as handle:
        handle.write(contents)


def freeze_data(frame, coverage, normalization, context, directory, retrieved_at):
    yahoo.validate_data(frame)  # Strict authoritative validator, no filtering.
    contents = canonical_csv(frame)
    source = directory / 'stage_a_adjusted_daily.csv'
    with source.open('xb') as handle:
        handle.write(contents)
    combined = digest(contents)
    symbols = {}
    for symbol in yahoo.STAGE_A_SYMBOLS:
        subset = frame[frame.symbol == symbol]
        corrections = normalization['symbols'][symbol]
        symbols[symbol] = dict(
            **coverage[symbol], first_usable_date=coverage[symbol]['first_date'],
            last_usable_date=coverage[symbol]['last_date'], row_count=len(subset),
            null_row_rejection_count=0, duplicate_date_count=0, invalid_ohlc_rejection_count=0,
            ohlc_boundary_correction_count=sum(corrections.values()),
            correction_categories=corrections, sha256=digest(canonical_csv(subset)),
        )
    manifest = dict(
        protocol_id=PROTOCOL_ID, data_loader_version='dx27.trend.stage_a.yahoo.v0.1',
        **context, retrieval_timestamp_utc=retrieved_at,
        symbols=list(yahoo.STAGE_A_SYMBOLS), requested_start='2003-01-01',
        requested_end_exclusive='2026-10-01', research_start='2005-01-01', research_last_date='2026-09-30',
        adjustment_method=yahoo.ADJUSTMENT_METHOD, history_parameters=yahoo.HISTORY_PARAMETERS,
        ohlc_boundary_normalization=normalization, per_symbol_metadata=symbols,
        combined_dataset_sha256=combined,
        canonical_representation='UTF-8 CSV; symbol,date,open,high,low,close,volume; symbol/date ascending; ISO dates; full precision; LF',
        rejection_count_scope='Returned provider rows only: successful strict validation rejects no rows; invalid inputs abort the entire run. Provider keepna=False filtering counts are unavailable.',
    )
    save_json(manifest, directory / 'trend_stage_a_data_manifest.json')
    assert_frozen(source, combined)
    return source, manifest


def six_metric_medians(metrics, winner):
    output = {}
    for split in ('selection', 'out_of_sample'):
        rows = [r for r in metrics if r.split == split and r.candidate_id == winner]
        output[split] = {}
        for metric, _ in METRIC_DIRECTIONS:
            values = pd.Series([r.values.get(metric) for r in rows], dtype='float64').dropna()
            output[split][metric] = float(values.median()) if len(values) else None
    return output


def summary_markdown(result, medians, manifest):
    lines = ['# Stage-A frozen research', '', f'Protocol: `{PROTOCOL_ID}`',
             f'Execution commit: `{manifest["execution_commit"]}`',
             f'Dataset SHA256: `{manifest["combined_dataset_sha256"]}`', '',
             '| Candidate | Selection mean rank | Selection p75 | Selection median | OOS mean rank | Locked status |',
             '|---|---:|---:|---:|---:|---|']
    oos = {r.candidate_id: r for r in result.oos_rankings}
    for r in result.selection_rankings:
        status = result.oos_validation_status if r.candidate_id == result.selection_winner else ''
        lines.append(f'| {r.candidate_id} | {r.mean_primary_rank:.6f} | {r.p75_primary_rank:.6f} | {r.median_primary_rank:.6f} | {oos[r.candidate_id].mean_primary_rank:.6f} | {status} |')
    lines += ['', 'Locked candidate primary metrics: unweighted medians of non-null symbol-level values across the 13 ETFs.', '',
              '| Metric | Selection | OOS |', '|---|---:|---:|']
    def display(value):
        return 'undefined' if value is None else f'{value:.10g}'
    for metric, _ in METRIC_DIRECTIONS:
        lines.append(f'| {metric} | {display(medians["selection"][metric])} | {display(medians["out_of_sample"][metric])} |')
    lines += ['', 'Sensitivity is descriptive only; no fragility threshold or winner override is defined by the frozen protocol.', '',
              '| Family | Pair | Selection agreement | OOS agreement | Agreement delta | Selection transition overlap | OOS transition overlap | Overlap delta |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in result.sensitivity_diagnostics:
        values = list(asdict(row).values())
        lines.append('| ' + ' | '.join([row.family, f'{row.candidate_a} / {row.candidate_b}', *[display(v) for v in values[3:]]]) + ' |')
    lines += ['', f'Provisional winner: `{result.selection_winner}`.',
              f'Final verdict: `STAGE_A_{result.oos_validation_status}`.',
              f'winner_selected = {str(result.winner_selected).lower()}',
              'production_trend_detector_created = false',
              'No OOS candidate replaces the locked selection winner. No model/formula/protocol changes after acquisition.', '']
    return '\n'.join(lines)


def run_research(output_dir):
    context = execution_context()
    if yahoo.OHLC_BOUNDARY_REL_TOL != 1e-12 or yahoo.OHLC_BOUNDARY_ABS_TOL != 1e-12:
        raise StageARunError('Frozen Yahoo boundary tolerance mismatch')
    destination = yahoo.output_directory(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise StageARunError('A new empty output directory is required; previous artifacts cannot be overwritten')
    destination.mkdir(parents=True, exist_ok=True)
    frame, coverage, normalization = yahoo.acquire_data()
    retrieved = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    source, manifest = freeze_data(frame, coverage, normalization, context, destination, retrieved)
    combined = manifest['combined_dataset_sha256']
    # Read only the frozen bytes, not an independently retained provider frame.
    assert_frozen(source, combined)
    frozen = read_csv(source)
    # Full pre-2005 warm-up is retained; no OOS price enters this invocation.
    selection_frame = frozen[frozen.date <= '2019-12-31'].copy()
    selection_tournament = run_tournament(selection_frame)
    selection_metrics = tuple(r for r in selection_tournament.metrics if r.split == 'selection')
    provisional = select_trend(selection_metrics)
    selection_csv = selection_ranking_csv(provisional).encode('utf-8')
    ranking_path = destination / 'trend_stage_a_selection_ranking.csv'
    with ranking_path.open('xb') as handle:
        handle.write(selection_csv)
    winner = provisional.selection_rankings[0]
    lock = dict(protocol_id=PROTOCOL_ID, execution_commit=context['execution_commit'],
                combined_dataset_sha256=combined, selection_period=dict(start='2005-01-01', end='2019-12-31'),
                eligible_candidate_ids=list(ELIGIBLE_IDS), provisional_selection_winner=provisional.selection_winner,
                winner_mean_rank=winner.mean_primary_rank, p75_rank=winner.p75_primary_rank,
                tie_break_values=dict(false_reversal_rate_20_symbol_median=winner.false_reversal_rate_20_symbol_median,
                                      directional_consistency_60_symbol_median=winner.directional_consistency_60_symbol_median,
                                      mae_60_symbol_median=winner.mae_60_symbol_median, candidate_id=winner.candidate_id),
                selection_ranking_sha256=digest(selection_csv))
    lock_path = destination / 'trend_stage_a_selection_lock.json'
    save_json(lock, lock_path)
    lock_hash = digest(lock_path.read_bytes())
    # OOS model evaluation starts only after the logical selection lock exists.
    assert_frozen(source, combined)
    assert_frozen(lock_path, lock_hash)
    assert_frozen(ranking_path, lock['selection_ranking_sha256'])
    complete = run_tournament(read_csv(source))
    assert_frozen(source, combined)
    assert_frozen(lock_path, lock_hash)
    result = select_trend(complete.metrics, complete.sensitivity)
    if result.selection_winner != lock['provisional_selection_winner'] or result.selection_rankings != provisional.selection_rankings:
        raise StageARunError('Locked selection result changed; no replacement is permitted')
    write_outputs(complete, destination / 'tournament')
    yahoo.check_tournament(destination / 'tournament', len(frozen))
    rows = [asdict(row) for row in result.oos_rankings]
    handle = io.StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    with (destination / 'trend_stage_a_oos_ranking.csv').open('x', encoding='utf-8', newline='') as out:
        out.write(handle.getvalue())
    medians = six_metric_medians(complete.metrics, result.selection_winner)
    report = json.loads(selection_report_json(result))
    locked_oos = next(r for r in result.oos_rankings if r.candidate_id == result.selection_winner)
    report.update(execution_commit=context['execution_commit'], combined_dataset_sha256=combined,
                  per_symbol_hashes={s: v['sha256'] for s, v in manifest['per_symbol_metadata'].items()},
                  data_quality_summary=manifest['per_symbol_metadata'],
                  ohlc_boundary_normalization=normalization, selection_lock_sha256=lock_hash,
                  locked_candidate_oos_mean_rank=locked_oos.mean_primary_rank,
                  locked_candidate_primary_symbol_medians=medians, final_verdict='STAGE_A_' + result.oos_validation_status)
    save_json(report, destination / 'trend_stage_a_report.json')
    with (destination / 'trend_stage_a_summary.md').open('x', encoding='utf-8', newline='') as out:
        out.write(summary_markdown(result, medians, manifest))
    assert_frozen(source, combined)
    assert_frozen(lock_path, lock_hash)
    if execution_context() != context:
        raise StageARunError('Source execution context changed during experiment')
    hashes = {p.relative_to(destination).as_posix(): digest(p.read_bytes())
              for p in sorted(destination.rglob('*')) if p.is_file()}
    save_json(hashes, destination / 'trend_stage_a_artifact_hashes.json')
    print(report['final_verdict'], 'locked candidate:', result.selection_winner,
          'winner_selected:', result.winner_selected)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        run_research(args.output_dir)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
