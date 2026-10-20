"""Fixed earnings-blackout comparison on the original, sealed SOXL sessions."""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

from soxl_earnings import MODES, apply_blackout, blackout_dates, latest_snapshot
from soxl_reversal import ARMS, block_intervals, groups, require, simulate, summarize


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trade_group(ledger):
    if not ledger:
        return dict(trades=0)
    s = summarize(ledger)
    return {k: s[k] for k in ('trades', 'wins', 'losses', 'net_trade_win_rate',
        'mean_trade_return_bps', 'average_win_bps', 'average_loss_bps', 'payoff_ratio',
        'profit_factor', 'worst_trade_bps', 'best_trade_bps')}


def run(sessions_path, output):
    import exchange_calendars as xc
    require(xc.__version__ == '4.13.2', 'FIXED_CALENDAR_REQUIRED')
    root = Path('docs/research/soxl-earnings')
    protocol = json.loads((root/'protocol.json').read_text())
    original = json.loads(Path(protocol['baseline']).read_text())
    require(sha(protocol['baseline']) == protocol['baseline_report_sha256'], 'BASELINE_REPORT_CHANGED')
    require(sha(sessions_path) == original['artifact_sha256']['sessions.json'], 'ORIGINAL_SESSIONS_CHANGED')
    require(sha('research/orb-diagnostics/soxl_reversal.py') == original['engine_sha256'],
            'ORIGINAL_ENGINE_CHANGED')
    audit = json.loads((root/'input-audit.json').read_text())
    for name, digest in audit['inputs_sha256'].items():
        require(sha(root/name) == digest, 'EVENT_OR_HOLDINGS_INPUT_CHANGED:' + name)
    require(protocol['primary_entry'] == '09:32' and protocol['primary_cost_bps_per_side'] == 5,
            'FIXED_PRIMARY_RULE_REQUIRED')
    require(protocol['uncertainty'] == dict(method='paired circular session block bootstrap',
            block_sessions=20, replicates=2000, seed=5807282), 'FIXED_BOOTSTRAP_REQUIRED')
    sessions = json.loads(Path(sessions_path).read_text())
    require(len(sessions) == original['data_quality']['valid_sessions'] and
            all('2016-01-01' <= s['date'] <= '2025-12-31' for s in sessions), 'ORIGINAL_SCOPE_REQUIRED')
    events = json.loads((root/'events.json').read_text())
    snapshots = json.loads((root/'holdings-snapshots.json').read_text())
    cal = xc.get_calendar('XNYS', start='2016-01-01', end='2026-01-06')
    calendar = [s.date().isoformat() for s in cal.sessions]
    watch = [dict(date=d, holdings=latest_snapshot(snapshots, d))
             for d in calendar if d <= '2025-12-31']
    baseline = {}
    for bps in (0, 2, 5, 10):
        for arm in ARMS:
            result = simulate(sessions, arm=arm, bps=bps)
            require(result['summary'] == original['cases'][f'09:32_{bps}bps'][arm],
                    'ORIGINAL_BASELINE_NOT_EXACT:' + arm + ':' + str(bps))
            baseline[(bps, arm)] = result
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for mode in MODES:
        excluded, evidence = blackout_dates(events, snapshots, calendar, mode)
        applicable = excluded & {s['date'] for s in sessions}
        by_year = Counter(d[:4] for d in applicable)
        case = dict(blackout_calendar_dates=sorted(excluded), valid_session_blackouts=len(applicable),
                    valid_session_blackouts_by_year=dict(sorted(by_year.items())),
                    event_evidence=evidence, cases={}, primary={})
        for bps in (0, 2, 5, 10):
            key = f'{bps}bps'
            case['cases'][key] = {}
            for arm in ARMS:
                before = baseline[(bps, arm)]['ledger']
                filtered = apply_blackout(before, excluded)
                after = summarize(filtered)
                case['cases'][key][arm] = after
                if bps == 5:
                    removed = [r for r in before if r['date'] in excluded and r['side']]
                    detail = dict(summary=after, unfiltered=baseline[(bps, arm)]['summary'],
                         removed_trades=trade_group(removed), by_year_and_partition=groups(filtered),
                         equity_change_vs_unfiltered=after['final_equity']-
                              baseline[(bps, arm)]['summary']['final_equity'])
                    if arm == 'GAP_DOWN_LONG':
                        ci = block_intervals(filtered, before)
                        ci['paired_mean_portfolio_daily_change_vs_unfiltered_bps95'] = ci.pop(
                              'mean_portfolio_daily_excess_vs_always_long_bps95')
                        detail['intervals'] = ci
                        (output/f'{mode}-daily.json').write_text(json.dumps(filtered, indent=2)+'\n')
                    case['primary'][arm] = detail
        # Original optimistic minute-boundary proxy remains supplementary.
        case['supplementary_0931_gap_down_long'] = {}
        for bps in (0, 2, 5, 10):
            base = simulate(sessions, arm='GAP_DOWN_LONG', entry='09:31', bps=bps)
            require(base['summary'] == original['cases'][f'09:31_{bps}bps']['GAP_DOWN_LONG'],
                    'ORIGINAL_0931_BASELINE_NOT_EXACT')
            case['supplementary_0931_gap_down_long'][f'{bps}bps'] = dict(unfiltered=base['summary'],
                       filtered=summarize(apply_blackout(base['ledger'], excluded)),
                       executable_quote_evidence=False)
        results[mode] = case
    report = dict(status='COMPLETE_RETROSPECTIVE_SOXX_MAJOR_EARNINGS_BLACKOUT_TEST',
       protocol_sha256=sha(root/'protocol.json'), input_audit_sha256=sha(root/'input-audit.json'),
       source_inputs_sha256=audit['inputs_sha256'], original_report_sha256=sha(protocol['baseline']),
       original_sessions_sha256=sha(sessions_path), original_16_primary_baselines_exact=True,
       original_four_0931_supplementary_baselines_exact=True,
       engine_sha256=sha('research/orb-diagnostics/soxl_earnings.py'), runner_sha256=sha(__file__),
       original_valid_sessions=len(sessions), target_calendar_sessions=len(watch),
       original_missing_session_selection_limit_retained=True,
       earnings_records=len(events), event_counts_by_issuer=dict(Counter(e['symbol'] for e in events)),
       holdings_snapshots=len(snapshots),
       disclosed_holdings_age_days=[min((date.fromisoformat(r['date'])-date.fromisoformat(r['holdings']['asof'])).days for r in watch),
                                     max((date.fromisoformat(r['date'])-date.fromisoformat(r['holdings']['asof'])).days for r in watch)],
       holdings_publication_lag_respected=True, exact_daily_constituents_or_weights_known=False,
       actual_future_earnings_schedule_known_at_entry_proven=False,
       preliminary_actual_results_included=2, guidance_only_updates_excluded=2,
       primary_date_mode=MODES[0], primary_entry='09:32', primary_cost_bps_per_side=5,
       results=results, independent_confirmation=False, strategy_promoted=False,
       actual_paper_orders=0, actual_live_orders=0,
       private_artifact_sha256={p.name: sha(p) for p in sorted(output.iterdir())})
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    for mode, case in results.items():
        p = case['primary']['GAP_DOWN_LONG']
        print(json.dumps(dict(mode=mode, blacked_out_sessions=case['valid_session_blackouts'],
                              primary=p['summary'], removed=p['removed_trades'], intervals=p['intervals']), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sessions', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    run(args.sessions, args.output)
