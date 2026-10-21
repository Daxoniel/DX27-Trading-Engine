"""Read-only coverage and public-action evidence review of frozen SM1 inputs.

Does not patch a price, simulate receipt, rerank securities or resume a halt.
Detailed schedules and provider responses remain private under work/.
"""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'research/sector-momentum'))
import study


def verify_evidence(root):
    """Bind retained derived pages to the four exact GET query/body hashes."""
    queries = {}
    for quality in ('complete', 'all'):
        queries[f'actions-{quality}.json'] = ('/v1/corporate-actions', dict(symbols='ETNB',
            start='2025-09-01', end='2025-12-31', data_quality=quality, limit=1000, sort='asc'))
    for adjustment in ('raw', 'all'):
        queries[f'bars-{adjustment}.json'] = ('/v2/stocks/bars', dict(symbols='ETNB',
            timeframe='1Day', start='2025-10-01', end='2025-11-05T23:59:59Z',
            adjustment=adjustment, asof='2025-04-25', feed='sip', sort='asc', limit=1000))
    for filename, (path, params) in queries.items():
        url = 'https://data.alpaca.markets' + path + '?' + urlencode(sorted(params.items()))
        key = sha256(url.encode()).hexdigest()
        meta = json.loads((root / 'pages' / (key + '.meta.json')).read_text())
        raw = gzip.decompress((root / 'pages' / (key + '.json.gz')).read_bytes())
        assert meta['url'] == url and meta['sha256'] == sha256(raw).hexdigest()
        assert meta['bytes'] == len(raw)
        body = json.loads(raw)
        assert not body.get('next_page_token'), 'SINGLE_PAGE_INCIDENT_REVIEW_REQUIRED'
        assert json.loads((root / filename).read_text()) == [body]


def coverage(adj, calendar, formations, mode, rules):
    gaps = []
    inspections = 0
    for i, f in enumerate(formations):
        if mode == 'spy' and i:
            break
        start = calendar[calendar.index(f['asof']) + 2]
        end = (calendar[calendar.index(formations[i + 1]['asof']) + 2]
               if mode != 'spy' and i + 1 < len(formations) else rules['mark_end'])
        for symbol in study.targets(f, mode, rules):
            missing = []
            for day in calendar:
                if start <= day <= end:
                    inspections += 1
                    if not study.positive(adj.get(symbol, {}).get(day)):
                        missing.append(day)
            if missing:
                gaps.append(dict(symbol=symbol, formation=f['asof'], entry=start,
                                 first_missing=missing[0], last_missing=missing[-1],
                                 missing_sessions=len(missing)))
    return dict(planned_symbol_session_checks=inspections, gaps=gaps)


def classify(provider_record, official):
    """Identity terms can agree while effective and process dates differ."""
    if official.get('right_tradable') is not False:
        raise ValueError('REVIEWED_NONTRADABLE_RIGHT_REQUIRED')
    identity = (provider_record.get('acquiree_symbol') == official['symbol'] and
                provider_record.get('acquiree_cusip') == official['cusip'])
    terms = (provider_record.get('cash_rate') == official['cash_per_share'] and
             provider_record.get('acquiree_rate') == 1 and
             provider_record.get('acquirer_rate') == 1 and
             provider_record.get('acquirer_cusip') == official['right_cusip'])
    return dict(identity_matches=identity, terms_match=terms,
                legal_effective_date=official['legal_effective_date'],
                vendor_effective_date=provider_record.get('effective_date'),
                vendor_process_date=provider_record.get('process_date'),
                vendor_payable_date=provider_record.get('payable_date'),
                date_conflict=provider_record.get('effective_date') != official['legal_effective_date'],
                destination_is_tradable_stock=False,
                broker_receipt_verified=False, automatic_resume_allowed=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    verify_evidence(a.evidence)
    original = PROJECT / 'docs/research/sector-momentum'
    rules = json.loads((original / 'protocol.json').read_text())
    for name, digest in json.loads((original / 'code-seal.json').read_text()).items():
        assert sha256((PROJECT / 'research/sector-momentum' / name).read_bytes()).hexdigest() == digest
    adj, raw, cohort, cal, _ = study.load(a.source / 'input-manifest.json', rules)
    ends = {d[:7]: d for d in cal if rules['formation_start'] <= d <= rules['formation_end']}
    formations = [study.features(d, adj, raw, cohort, cal, rules) for d in sorted(ends.values())]
    assert formations == json.loads((a.source / 'formations.json').read_text())
    details = {mode: coverage(adj, cal, formations, mode, rules)
               for mode in ('ordinary', 'relative', 'broad', 'spy')}
    a.evidence.mkdir(parents=True, exist_ok=True)
    (a.evidence / 'planned-coverage.json').write_text(json.dumps(details, indent=2) + '\n')
    official = json.loads((PROJECT / 'docs/research/sector-action-review/event.json').read_text())
    pages = json.loads((a.evidence / 'actions-complete.json').read_text())
    assert pages == json.loads((a.evidence / 'actions-all.json').read_text())
    records = [r for page in pages for r in page['corporate_actions'].get('stock_and_cash_mergers', [])]
    matching = [r for r in records if r.get('acquiree_symbol') == official['symbol']]
    assert len(matching) == 1
    assessment = classify(matching[0], official)
    assert assessment['identity_matches'] and assessment['terms_match']
    # Confirm fresh raw and adjusted daily responses stop where the exchange says.
    confirmations = {}
    for adjustment in ('raw', 'all'):
        pages = json.loads((a.evidence / f'bars-{adjustment}.json').read_text())
        rows = [r for page in pages for r in page.get('bars', {}).get(official['symbol'], [])]
        days = [r['t'][:10] for r in rows]
        assert len(days) == len(set(days)) and max(days) == official['last_trading_date']
        confirmations[adjustment] = dict(rows=len(rows), last_session=max(days),
                                       post_last_session_rows=0)
    # The sole gap must reconcile to the actual pre-halt ledger in BOTH cost cases.
    incidents = details['broad']['gaps']
    assert len(incidents) == 1 and incidents[0]['symbol'] == official['symbol']
    assert incidents[0]['first_missing'] == official['legal_effective_date']
    for bps in (5, 25):
        r = json.loads((a.source / f'broad-{bps}bp.json').read_text())
        assert r['summary']['halt']['date'] == incidents[0]['first_missing']
        assert official['symbol'] in r['events'][-1]['new_values']
        assert r['summary']['proxy_return'] is None
    summary = dict(scope='RETROSPECTIVE_COVERAGE_AND_CORPORATE_ACTION_DIAGNOSIS',
        original_result_changed=False, original_full_period_control_return=None,
        planned_coverage={mode: dict(planned_symbol_session_checks=r['planned_symbol_session_checks'],
            gap_intervals=len(r['gaps']), unique_gap_securities=len({g['symbol'] for g in r['gaps']}),
            missing_symbol_sessions=sum(g['missing_sessions'] for g in r['gaps'])) for mode, r in details.items()},
        event_assessment=assessment, fresh_bars=confirmations,
        source_manifest_sha256=sha256((a.source / 'input-manifest.json').read_bytes()).hexdigest(),
        formations_recomputed_and_unchanged=len(formations), actual_orders=0,
        quote_or_broker_execution_verified=False, promotable=False)
    # Hash retained raw evidence without publishing provider payloads or private holdings.
    summary['evidence_files'] = [dict(path=p.name, sha256=sha256(p.read_bytes()).hexdigest())
        for p in sorted(a.evidence.glob('*.json')) if p.name != 'planned-coverage.json']
    summary['response_pages'] = [dict(request_sha256=p.name.split('.')[0],
        **{k: json.loads(p.read_text())[k] for k in ('sha256', 'bytes', 'retrieved_at')})
        for p in sorted((a.evidence / 'pages').glob('*.meta.json'))]
    a.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary['planned_coverage'], indent=2))


if __name__ == '__main__':
    main()
