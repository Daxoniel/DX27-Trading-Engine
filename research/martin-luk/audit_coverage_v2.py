"""Audit saved candidate coverage artifacts without importing either scanner."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path


def audit(root):
    summary = json.loads((root/'summary.json').read_text())
    counts = {v:Counter() for v in ('MLP1','MLP2')}
    symbols = {v:set() for v in counts}
    sessions = Counter()
    exclusions = Counter()
    dates = []
    for ref in summary['sessions_manifest']:
        raw = gzip.decompress((root/ref['path']).read_bytes())
        if sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('PLAN_DIGEST_MISMATCH')
        payload = json.loads(raw)
        dates.append(payload['date'])
        plans = payload['plans']
        if plans['MLP1']['input_sha256'] != plans['MLP2']['input_sha256']:
            raise ValueError('DIFFERENT_COMPARISON_INPUTS')
        excluded = [x['symbol'] for x in payload['excluded']]
        exclusions.update(x['reason'] for x in payload['excluded'])
        universes = []
        for version,p in plans.items():
            if p['execution_enabled'] or p['version'] != version:
                raise ValueError('WRONG_VERSION_OR_EXECUTION_ENABLED')
            watched = [x['symbol'] for x in p['watchlist']]
            rejected = [x['symbol'] for x in p['rejected']]
            all_names = watched + rejected + excluded
            if len(all_names) != len(set(all_names)) or len(all_names) != summary['cohort_records']:
                raise ValueError('UNIVERSE_ACCOUNTING_FAILED')
            universes.append(set(all_names))
            counts[version].update(x['reason'] for x in p['rejected'])
            counts[version]['WATCHLIST'] += len(watched)
            symbols[version].update(watched)
            sessions[version] += bool(watched)
            if version == 'MLP2':
                for c in p['watchlist']:
                    if p['sector_leaders'][c['sector']] < p['rules']['min_sector_peers']:
                        raise ValueError('SECTOR_GATE_FAILED')
        if universes[0] != universes[1]:
            raise ValueError('DIFFERENT_UNIVERSES')
    if dates != sorted(set(dates)) or len(dates) != summary['sessions']:
        raise ValueError('SESSION_ACCOUNTING_FAILED')
    if dict(exclusions) != summary['exclusions']:
        raise ValueError('EXCLUSION_TOTAL_MISMATCH')
    for v,expected in summary['versions'].items():
        observed = dict(funnel=dict(counts[v]), unique_symbols=len(symbols[v]),
                        sessions_with_candidates=sessions[v])
        if observed != expected:
            raise ValueError('SUMMARY_TOTAL_MISMATCH')
    return dict(status='PASS', sessions_checked=len(dates),
        stock_sessions_accounted=summary['cohort_records']*len(dates),
        checks=['plan_digests','identical_input_hashes','identical_universe_partition',
                'no_duplicate_or_unaccounted_names','version_and_execution_flags',
                'MLP2_sector_gate','session_uniqueness','reconstructed_summary'],
        summary_sha256=sha256((root/'summary.json').read_bytes()).hexdigest(),
        limitation='Artifact accounting only; not independent market-source or profitability validation.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.write_text(json.dumps(audit(args.root),indent=2)+'\n')
