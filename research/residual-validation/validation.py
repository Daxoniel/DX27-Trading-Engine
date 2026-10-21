"""Frozen temporal validation adapters; the parent signal/account code is reused."""
import argparse
from copy import deepcopy
from datetime import date
import csv
import gzip
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import sys
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT/'research/residual-momentum'))
import runner as rm


class IntegrityError(ValueError):
    def __init__(self, details):
        super().__init__('FORWARD_OVERLAP_MISMATCH')
        self.details = details


def join_forward(old, new):
    """Exact Dec-2025 seam; no rebasing, price filling or ticker filtering."""
    if set(old) != set(new):
        raise ValueError('FORWARD_SYMBOL_SET_MISMATCH')
    issues = []; checked = 0
    for symbol in old:
        left = {d: v for d, v in old[symbol].items() if d.startswith('2025-12')}
        right = {d: v for d, v in new[symbol].items() if d.startswith('2025-12')}
        if left != right:
            issues.append(dict(symbol=symbol, date_set_equal=set(left)==set(right),
                               old_dates=len(left), new_dates=len(right)))
        checked += len(left)
    if issues:
        raise IntegrityError(issues)
    result = {s: dict(rows) for s, rows in old.items()}
    for symbol, rows in new.items():
        for day, value in rows.items():
            if not '2025-12-01' <= day <= '2026-09-30':
                raise ValueError('UNREGISTERED_FORWARD_DATE')
            if day >= '2026-01-01':
                result[symbol][day] = value
    return result, checked


def quarantine_forward(old, new, calendar, formations):
    """RV1a: only nonparticipants proven ineligible from retained past gaps."""
    filtered = dict(new); blocked = []; proof = []
    for symbol in old:
        old_has = any(day.startswith('2025-12') for day in old[symbol])
        new_has = any(day.startswith('2025-12') for day in new.get(symbol,{}))
        if old_has or not new_has:
            continue
        counts = []
        for day in formations:
            end = calendar.index(day); window = calendar[max(0,end-252):end+1]
            missing = sum(d.startswith('2025-12') and d not in old[symbol] for d in window)
            if len(window)!=253 or missing==0:
                raise ValueError('QUARANTINE_COULD_CHANGE_ELIGIBILITY')
            counts.append(missing)
        if not formations:
            raise ValueError('QUARANTINE_FORMATIONS_REQUIRED')
        filtered[symbol] = {}; blocked.append(symbol); proof.append(counts)
    aggregate = [dict(formation=day, quarantined_symbols=len(blocked),
        minimum_old_missing_beta_window_sessions=min((row[i] for row in proof),default=0))
        for i,day in enumerate(formations)]
    return filtered, blocked, aggregate


def read_factors(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith('.csv')]
        assert len(names)==1 and archive.getinfo(names[0]).file_size <= 5_000_000
        text = archive.read(names[0]).decode('utf-8-sig')
    factors = {}; header = False
    for row in csv.reader(io.StringIO(text)):
        if len(row)>=5 and [v.strip() for v in row[:5]]==['','Mkt-RF','SMB','HML','RF']:
            header = True; continue
        if not header or len(row)<5 or len(row[0].strip())!=6 or not row[0].strip().isdigit():
            continue
        month = row[0].strip()[:4]+'-'+row[0].strip()[4:]
        if not '2022-12' <= month <= '2026-07':
            continue
        values = [float(v) for v in row[1:5]]
        if month in factors or any(not math.isfinite(v) or v in (-99.99,-999.) for v in values):
            raise ValueError('INVALID_FACTOR_MONTH')
        factors[month] = [v/100 for v in values]
    expected = [rm.parent.shift_month(date(2022,12,1), i) for i in range(44)]
    if sorted(factors)!=expected:
        raise ValueError('FACTOR_COVERAGE_FAILED')
    return factors


def screen(runs):
    primary = [runs[f'{selector}-{bps}bp']['summary']
               for bps in (5,25) for selector in ('matched_ordinary','matched_residual')]
    if any(s['halt'] or s['proxy_return'] is None for s in primary):
        return dict(status='INCOMPLETE', checks={}, automatic_promotion=False)
    checks = {}
    for bps in (5,25):
        base = runs[f'matched_ordinary-{bps}bp']['summary']; residual = runs[f'matched_residual-{bps}bp']['summary']
        freq = lambda s: s['positive_stock_return_intervals']/s['stock_return_intervals'] if s['stock_return_intervals'] else 0
        checks[str(bps)] = dict(return_positive=residual['proxy_return']>0,
            beats_matched_return=residual['proxy_return']>base['proxy_return'],
            drawdown_within_budget=residual['observed_daily_drawdown']<=.25,
            drawdown_no_worse=residual['observed_daily_drawdown']<=base['observed_daily_drawdown'],
            gross_positive_frequency_at_least_half=freq(residual)>=.5,
            gross_positive_frequency_no_worse=freq(residual)>=freq(base))
    passed = all(v for row in checks.values() for v in row.values())
    return dict(status='PASS' if passed else 'FAIL', checks=checks, automatic_promotion=False)


def read_batches(root, refs):
    result = {}
    for ref in refs:
        raw = gzip.decompress((root/ref['path']).read_bytes())
        assert sha256(raw).hexdigest()==ref['sha256']
        batch = json.loads(raw)
        if set(batch)&set(result):
            raise ValueError('DUPLICATE_BATCH_SYMBOL')
        for rows in batch.values():
            dates = [r['t'][:10] for r in rows]
            if dates!=sorted(set(dates)):
                raise ValueError('DUPLICATE_OR_UNSORTED_DATE')
        result.update(batch)
    if 'SOXL' in result:
        raise ValueError('RESERVED_SYMBOL_PROHIBITED')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True); a = p.parse_args()
    public = PROJECT/'docs/research/residual-validation'; protocol_path = public/'protocol.json'
    rules = json.loads(protocol_path.read_text()); seal = json.loads((public/'code-seal-v2.json').read_text())
    assert sha256((public/'input-amendment.json').read_bytes()).hexdigest()==seal['amendment_sha256']
    for name, digest in seal['files'].items():
        assert sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==digest
    parent_public = PROJECT/'docs/research/residual-momentum'
    parent_rules = json.loads((parent_public/'protocol.json').read_text())
    assert sha256((parent_public/'protocol.json').read_bytes()).hexdigest()==rules['parent_protocol_sha256']
    for name, digest in json.loads((parent_public/'code-seal-v2.json').read_text())['files'].items():
        assert sha256((PROJECT/'research/residual-momentum'/name).read_bytes()).hexdigest()==digest
    original = json.loads((PROJECT/'docs/research/sector-momentum/protocol.json').read_text())
    source = PROJECT/'work/sector-momentum/input-manifest.json'
    assert sha256(source.read_bytes()).hexdigest()==rules['parent_manifest_sha256']
    adj, raw, cohort, old_calendar, _ = rm.parent.load(source, original)
    manifest_path = a.root/'input-manifest.json'; manifest = json.loads(manifest_path.read_text())
    assert manifest['protocol_sha256']==sha256(protocol_path.read_bytes()).hexdigest()
    assert manifest['source_cohort_sha256']==rules['cohort_sha256']
    digest = sha256(manifest_path.read_bytes()).hexdigest()
    adjusted = read_batches(a.root, manifest['inputs']['adjusted_new'])
    fresh_raw = read_batches(a.root, manifest['inputs']['raw_new'])
    adj_new = {s: {r['t'][:10]:r['c'] for r in rows} for s, rows in adjusted.items()}
    # SPY has no old raw reference and is never in the stock liquidity universe.
    raw_new = {s: {r['t'][:10]:(r['c'],r['v']) for r in rows} for s, rows in fresh_raw.items() if s!='SPY'}
    calendar_blob = (a.root/'calendar.json').read_bytes()
    assert sha256(calendar_blob).hexdigest()==manifest['calendar_sha256']
    expected = json.loads(calendar_blob)
    proof_calendar = sorted(set(old_calendar)|set(expected))
    formation_days = sorted({d[:7]:d for d in proof_calendar if rules['formation_start']<=d<=rules['formation_end']}.values())
    assert len(formation_days)==9
    adj_new, forward_blocked, quarantine_proof = quarantine_forward(adj,adj_new,proof_calendar,formation_days)
    for symbol in forward_blocked:
        raw_new[symbol] = {d:v for d,v in raw[symbol].items() if d.startswith('2025-12')}
    (a.root/'quarantined-forward-identities.json').write_text(json.dumps(forward_blocked)+'\n')
    try:
        prices, adj_checks = join_forward(adj, adj_new)
        raw_prices, raw_checks = join_forward(raw, raw_new)
    except IntegrityError as error:
        (a.root/'seam-failure-details.json').write_text(json.dumps(error.details,indent=2)+'\n')
        receipt = dict(status='ABORTED_INPUT_VALIDATION', code=str(error), affected_symbols=len(error.details),
            details_sha256=sha256((a.root/'seam-failure-details.json').read_bytes()).hexdigest(),
            scores_computed=False, screen='INCOMPLETE', actual_orders=0)
        (a.root/'integrity-v2.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps(receipt)); return
    history = read_batches(a.root, manifest['inputs']['history'])
    history, quarantined = rm.quarantine_unresolved(adj, history)
    prices, history_checks = rm.extend_prices(prices, history)
    (a.root/'quarantined-identities.json').write_text(json.dumps(quarantined)+'\n')
    if [d for d in sorted(prices['SPY']) if d>='2025-12-01'] != expected:
        raise ValueError('FORWARD_BENCHMARK_CALENDAR_MISMATCH')
    calendar = sorted(prices['SPY']); factor_blob = (a.root/'ff3.zip').read_bytes()
    assert sha256(factor_blob).hexdigest()==rules['factor_file_sha256']==manifest['factor_sha256']
    factors = read_factors(factor_blob)
    runtime = deepcopy(original)
    for key in ('formation_start','formation_end','mark_end','initial_proxy_capital'):
        runtime[key] = rules[key]
    ends = {d[:7]: d for d in calendar if rules['formation_start']<=d<=rules['formation_end']}
    assert len(ends)==9
    formations = [rm.parent.features(d,prices,raw_prices,cohort,calendar,runtime) for d in sorted(ends.values())]
    base_checks = rm.account.verify_features(formations,prices,raw_prices,calendar,runtime)
    matched, coverage, score_checks = rm.matched_features(formations,prices,calendar,factors,parent_rules)
    (a.root/'formations.json').write_text(json.dumps(formations,sort_keys=True)+'\n')
    (a.root/'matched-features.json').write_text(json.dumps(matched,sort_keys=True)+'\n')
    result = dict(scope=rules['scope'], coverage=coverage, independent_eligible_feature_checks=base_checks,
        input_amendment='RV1a', quarantined_forward_symbols=len(forward_blocked), quarantine_proof=quarantine_proof,
        independent_score_checks=score_checks, adj_forward_overlap=adj_checks, raw_forward_overlap=raw_checks,
        history_overlap=history_checks, quarantined_history_symbols=len(quarantined),
        retained_factor_months=len(factors), runs={}, independent_case_audits={}, actual_orders=0,
        input_manifest_sha256=digest, independent_out_of_sample_certified=False, promotable=False)
    selections = {}
    for selector in rules['selectors']:
        transformed = rm.adapt(formations,matched,selector)
        selections[selector] = [set(rm.parent.targets(f,'ordinary',runtime)) for f in transformed]
        for bps in rules['costs_bps_per_side']:
            case = rm.parent.run(prices,calendar,transformed,'ordinary',bps,runtime)
            case['summary'].update(selector=selector,input_manifest_sha256=digest,code_seal=seal)
            key = f'{selector}-{bps}bp'; path = a.root/(key+'.json')
            path.write_text(json.dumps(case,sort_keys=True)+'\n')
            audit = rm.account.audit_case(path,prices,calendar,transformed,runtime,digest,seal)
            result['independent_case_audits'][key] = audit
            result['runs'][key] = dict(summary=case['summary'],nav=case['nav'],intervals=case['intervals'])
            print(key,json.dumps({k:v for k,v in case['summary'].items() if k!='code_seal'}),flush=True)
    result['screen'] = screen(result['runs'])
    result['selection_overlaps'] = {s: [len(a&b) for a,b in zip(selections['matched_residual'],seq)]
        for s,seq in selections.items() if s!='matched_residual'}
    (a.root/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('SCREEN',result['screen']['status'])


if __name__=='__main__':
    main()
