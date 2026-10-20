"""Compare frozen MLP1 and MLP2 candidate coverage on identical vendor daily bars.

No returns or orders. Read existing private history cache; write private plans.
"""
import argparse
from collections import Counter
from datetime import timedelta
import gzip
from hashlib import sha256
import json
from pathlib import Path

from history_screen import split_adjust
from strategy import canonical, scan as scan_v1, stamp
from strategy_v2 import scan as scan_v2


def snapshot_for(session, prior, metadata, source, splits):
    asof = stamp(session['open']) - timedelta(minutes=30)
    assets, excluded = [], []
    for m in metadata:
        symbol = m['symbol']
        raw = [source.get(symbol, {}).get(s['date']) for s in prior]
        if any(b is None for b in raw):
            excluded.append(dict(symbol=symbol, reason='MISSING_DAILY_HISTORY'))
            continue
        adjusted = split_adjust(raw, session['date'], splits.get(symbol, []))
        daily = [dict(start=s['open'], end=s['close'],
            # Synthetic knowledge clock for retrospective final daily records;
            # NOT a claim that the final correction arrived at this timestamp.
            available_at=asof.isoformat(), open=b['o'], high=b['h'],
            low=b['l'], close=b['c'], volume=b['v']) for s,b in zip(prior,adjusted)]
        from strategy import validate_bars
        try:
            validate_bars(daily, asof)
        except (ValueError, TypeError):
            excluded.append(dict(symbol=symbol, reason='INVALID_DAILY_HISTORY'))
            continue
        assets.append(dict(symbol=symbol, sector=m['sector'], kind='US_COMMON_STOCK',
            tradable=True, known_at='2025-04-25T20:19:02Z', daily=daily))
    return dict(asof=asof.isoformat(), session_open=session['open'],
        session_close=session['close'], previous_session_close=prior[-1]['close'],
        universe_kind='DIAGNOSTIC_SURVIVOR_BIASED', price_basis='ASOF_SPLIT_ADJUSTED',
        adjustment_asof=asof.isoformat(), history_schedule=[(s['open'],s['close']) for s in prior],
        daily_bar_convention='VENDOR_1DAY_FINAL_REVISED_NOT_RTH_AGGREGATE', assets=assets), excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((args.root/'cohort.json').read_text())
    schedule = json.loads((args.root/'schedule.json').read_text())
    splits = json.loads((args.root/'splits.json').read_text())
    source, inputs = {}, {}
    for f in sorted((args.root/'daily').glob('*.gz')):
        raw = f.read_bytes()
        inputs[str(f.relative_to(args.root))] = sha256(raw).hexdigest()
        for symbol, rows in json.loads(gzip.decompress(raw)).items():
            dates = [b['t'][:10] for b in rows]
            if len(set(dates)) != len(dates) or symbol in source:
                raise ValueError('DUPLICATE_SOURCE_RECORD')
            source[symbol] = dict(zip(dates, rows))
    for name in ('cohort.json','schedule.json','splits.json'):
        inputs[name] = sha256((args.root/name).read_bytes()).hexdigest()
    totals = {v: Counter() for v in ('MLP1','MLP2')}
    names = {v: set() for v in totals}
    dates = {v: 0 for v in totals}
    exclusions = Counter()
    records = []
    for i,s in enumerate(schedule):
        if not '2025-04-28' <= s['date'] <= '2025-12-31':
            continue
        prior = schedule[i-160:i]
        if len(prior) != 160:
            raise ValueError('INSUFFICIENT_CALENDAR')
        snapshot, excluded = snapshot_for(s, prior, metadata, source, splits)
        exclusions.update(x['reason'] for x in excluded)
        plans = {}
        for version, scanner in (('MLP1',scan_v1),('MLP2',scan_v2)):
            plan = scanner(snapshot)
            plans[version] = plan
            totals[version].update(x['reason'] for x in plan['rejected'])
            totals[version]['WATCHLIST'] += len(plan['watchlist'])
            names[version].update(x['symbol'] for x in plan['watchlist'])
            dates[version] += bool(plan['watchlist'])
        payload = dict(date=s['date'], plans=plans, excluded=excluded)
        raw = canonical(payload).encode()
        filename = s['date']+'.json.gz'
        (args.output/filename).write_bytes(gzip.compress(raw, mtime=0))
        records.append(dict(path=filename, sha256=sha256(raw).hexdigest()))
        print(s['date'], *(len(plans[v]['watchlist']) for v in totals), flush=True)
    result = dict(stage='CANDIDATE_COVERAGE_ONLY', sessions=len(records),
        cohort_records=len(metadata), exclusions=dict(exclusions),
        versions={v:dict(funnel=dict(totals[v]), unique_symbols=len(names[v]),
            sessions_with_candidates=dates[v]) for v in totals},
        input_sha256=inputs, sessions_manifest=records,
        code_sha256={n:sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
            for n in ('strategy.py','strategy_v2.py','history_screen.py','scan_history_v2.py')},
        actual_orders=0, profitability_tested=False, independent_out_of_sample=False)
    (args.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
