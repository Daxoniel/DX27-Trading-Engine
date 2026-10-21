"""Frozen matched-history score experiment; no orders or quote interpolation."""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from features import parse_factors, score
from audit import independent_score, verify

PROJECT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


parent = module('rm1_parent', PROJECT/'research/sector-momentum/study.py')
account = module('rm1_parent_account', PROJECT/'research/sector-momentum/audit.py')


def extend_prices(adj, extension):
    result = {s: dict(rows) for s, rows in adj.items()}; checked = 0
    for symbol, rows in extension.items():
        if symbol not in result:
            raise ValueError('EXTENSION_IDENTITY_UNKNOWN')
        fresh = {r['t'][:10]: r['c'] for r in rows}
        if len(fresh) != len(rows):
            raise ValueError('DUPLICATE_EXTENSION_DATE')
        old_overlap = {d: c for d, c in result[symbol].items() if '2023-01-01' <= d <= '2023-01-31'}
        new_overlap = {d: c for d, c in fresh.items() if '2023-01-01' <= d <= '2023-01-31'}
        if old_overlap != new_overlap:
            raise ValueError('ADJUSTED_VINTAGE_OVERLAP_MISMATCH')
        checked += len(old_overlap)
        for day, close in fresh.items():
            if not '2022-03-01' <= day <= '2023-01-31':
                raise ValueError('UNREGISTERED_EXTENSION_DATE')
            if day < '2023-01-01':
                result[symbol][day] = close
    return result, checked


def quarantine_unresolved(adj, extension):
    """RM1a: discard new histories whose overlap exists only in the new query."""
    retained = {}; excluded = []
    for symbol, rows in extension.items():
        old_has = any(day.startswith('2023-01') for day in adj.get(symbol, {}))
        new_has = any(row['t'].startswith('2023-01') for row in rows)
        if not old_has and new_has:
            excluded.append(symbol)
        else:
            retained[symbol] = rows
    return retained, excluded


def matched_features(formations, prices, calendar, factors, rules):
    detailed = []; coverage = []; checks = 0
    for f in formations:
        rows = []; rejected = Counter()
        for row in f['eligible']:
            try:
                feature = score(row['symbol'], f['asof'], prices, calendar, factors, rules)
            except ValueError as error:
                if str(error) not in ('MONTHLY_STOCK_HISTORY_MISSING', 'SCORE_DISPERSION_TOO_SMALL'):
                    raise
                rejected[str(error)] += 1; continue
            verify(feature, independent_score(row['symbol'], f['asof'], prices, calendar, factors))
            rows.append(dict(row, residual_feature=feature)); checks += 1
        detailed.append(dict(asof=f['asof'], eligible=rows))
        coverage.append(dict(formation=f['asof'], original_eligible=len(f['eligible']),
            matched_eligible=len(rows), rejected=dict(rejected)))
    return detailed, coverage, checks


def adapt(formations, matched, selector):
    if selector not in ('parent_ordinary', 'matched_ordinary', 'matched_relative', 'matched_residual'):
        raise ValueError('UNKNOWN_SELECTOR')
    result = deepcopy(formations if selector == 'parent_ordinary' else matched)
    for f in result:
        for row in f['eligible']:
            if selector == 'matched_relative':
                row['momentum'] = row['relative']
            elif selector == 'matched_residual':
                row['momentum'] = row['residual_feature']['score']
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True); p.add_argument('--root', type=Path, required=True)
    a = p.parse_args(); public = PROJECT/'docs/research/residual-momentum'
    protocol_path = public/'protocol.json'; rules = json.loads(protocol_path.read_text())
    manifest_path = a.root/'input-manifest.json'; manifest = json.loads(manifest_path.read_text())
    digest = sha256(manifest_path.read_bytes()).hexdigest(); seal = json.loads((public/'code-seal-v2.json').read_text())
    amendment_path = public/'input-amendment.json'; amendment = json.loads(amendment_path.read_text())
    assert sha256(amendment_path.read_bytes()).hexdigest() == seal['amendment_sha256']
    assert amendment['original_protocol_sha256'] == sha256(protocol_path.read_bytes()).hexdigest()
    assert manifest['protocol_sha256'] == sha256(protocol_path.read_bytes()).hexdigest()
    assert manifest['parent_manifest_sha256'] == rules['parent_manifest_sha256']
    for name, h in seal['files'].items():
        assert sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == h
    old_path = PROJECT/'docs/research/sector-momentum/protocol.json'
    assert sha256(old_path.read_bytes()).hexdigest() == rules['parent_protocol_sha256']
    assert sha256((a.source/'input-manifest.json').read_bytes()).hexdigest() == rules['parent_manifest_sha256']
    for name, h in json.loads((old_path.parent/'code-seal.json').read_text()).items():
        assert sha256((PROJECT/'research/sector-momentum'/name).read_bytes()).hexdigest() == h
    original = json.loads(old_path.read_text())
    adj, raw, cohort, cal, _ = parent.load(a.source/'input-manifest.json', original)
    ends = {d[:7]: d for d in cal if original['formation_start'] <= d <= original['formation_end']}
    formations = [parent.features(d, adj, raw, cohort, cal, original) for d in sorted(ends.values())]
    assert sha256((a.source/'formations.json').read_bytes()).hexdigest() == rules['parent_formations_sha256']
    assert formations == json.loads((a.source/'formations.json').read_text())
    extension = {}
    for ref in manifest['extension']:
        blob = gzip.decompress((a.root/ref['path']).read_bytes())
        assert sha256(blob).hexdigest() == ref['sha256']
        batch = json.loads(blob)
        if set(batch)&set(extension):
            raise ValueError('DUPLICATE_EXTENSION_SYMBOL')
        extension.update(batch)
    assert set(extension) == {r['symbol'] for f in formations for r in f['eligible']}|{'SPY'}
    extension, excluded = quarantine_unresolved(adj, extension)
    (a.root/'quarantined-identities.json').write_text(json.dumps(excluded)+'\n')
    prices, overlap = extend_prices(adj, extension); calendar = sorted(prices['SPY'])
    factor_blob = (a.root/'ff3.zip').read_bytes()
    assert sha256(factor_blob).hexdigest() == manifest['factors']['sha256']
    factors = parse_factors(factor_blob)
    matched, coverage, checks = matched_features(formations, prices, calendar, factors, rules)
    (a.root/'matched-features.json').write_text(json.dumps(matched, sort_keys=True)+'\n')
    result = dict(scope=rules['scope'], coverage=coverage, independent_score_checks=checks,
        input_amendment=amendment['version'], quarantined_extension_symbols=len(excluded),
        seam_overlap_symbol_sessions=overlap, retained_factor_months=len(factors), runs={},
        independent_case_audits={}, input_manifest_sha256=digest, actual_orders=0,
        independent_out_of_sample=False, promotable=False)
    selections = {}
    for selector in rules['selectors']:
        transformed = adapt(formations, matched, selector)
        selections[selector] = [set(parent.targets(f, 'ordinary', original)) for f in transformed]
        for bps in rules['costs_bps_per_side']:
            case = parent.run(prices, calendar, transformed, 'ordinary', bps, original)
            case['summary'].update(selector=selector, input_manifest_sha256=digest, code_seal=seal)
            key = f'{selector}-{bps}bp'; path = a.root/(key+'.json')
            path.write_text(json.dumps(case, sort_keys=True)+'\n')
            audited = account.audit_case(path, prices, calendar, transformed, original, digest, seal)
            if selector == 'parent_ordinary':
                old = json.loads((a.source/f'ordinary-{bps}bp.json').read_text())
                assert case['nav'] == old['nav'], 'PARENT_NAV_CHANGED'
            result['independent_case_audits'][key] = audited
            # Omit per-name positions and raw prices from the public aggregate.
            result['runs'][key] = dict(summary=case['summary'], nav=case['nav'], intervals=case['intervals'])
            print(key, json.dumps(case['summary']), flush=True)
    result['selection_overlaps'] = {selector: [len(a&b) for a, b in zip(selections['matched_residual'], values)]
        for selector, values in selections.items() if selector != 'matched_residual'}
    (a.root/'results.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
