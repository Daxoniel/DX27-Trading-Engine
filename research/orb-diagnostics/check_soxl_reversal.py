"""Run the fixed SOXL protocol on private, hash-verified historical captures."""
import argparse
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

from soxl_reversal import (ARMS, ENTRIES, block_intervals, break_even_bps,
                           diagnostic_buckets, groups, regression, require, simulate,
                           summarize)


NY = ZoneInfo('America/New_York')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_bar(bar):
    prices = [bar[k] for k in ('o', 'h', 'l', 'c')]
    return (all(isinstance(x, (int, float)) and not isinstance(x, bool) and
                math.isfinite(x) and x > 0 for x in prices) and
            bar['l'] <= min(bar['o'], bar['c']) <= max(bar['o'], bar['c']) <= bar['h'] and
            isinstance(bar['v'], (int, float)) and math.isfinite(bar['v']) and bar['v'] >= 0)


def assemble(calendar, minutes, ex_dates):
    """Calendar includes warmup. A missing preceding close never bridges a gap."""
    sessions, excluded = [], []
    for i, (day, close_time) in enumerate(calendar):
        if not '2016-01-01' <= day <= '2025-12-31':
            continue
        reason = []
        data = minutes.get(day, {})
        times = [f'09:{minute:02}' for minute in range(30, 60)] + ['10:00']
        missing = [t for t in times if t not in data]
        if missing:
            reason.append('MISSING_OPENING_MINUTES:' + ','.join(missing))
        invalid = [t for t in times if t in data and not validate_bar(data[t])]
        if invalid:
            reason.append('INVALID_OPENING_MINUTES:' + ','.join(invalid))
        previous_day, previous_close_time = calendar[i-1] if i else (None, None)
        previous_bar = minutes.get(previous_day, {}).get(previous_close_time)
        if previous_bar is None:
            reason.append('MISSING_EXACT_PREVIOUS_SESSION_FINAL_MINUTE')
        elif not validate_bar(previous_bar):
            reason.append('INVALID_PREVIOUS_SESSION_FINAL_MINUTE')
        if reason:
            excluded.append(dict(date=day, reasons=reason))
            continue
        previous_prices = []
        for prior_day, prior_close in calendar[max(0, i-21):i]:
            b = minutes.get(prior_day, {}).get(prior_close)
            if b and validate_bar(b):
                previous_prices.append(b['c'])
        vol = None
        if len(previous_prices) == 21:
            vol = statistics.stdev(b/a-1 for a, b in zip(previous_prices, previous_prices[1:]))
        sessions.append(dict(date=day, previous_date=previous_day,
              previous_close=previous_bar['c'], gap=data['09:30']['o']/previous_bar['c']-1,
              minutes={t: data[t] for t in times}, ex_dividend=day in ex_dates,
              previous_20_session_vol=vol))
    return sessions, excluded


def prepare(source, secondary):
    import exchange_calendars as xc
    require(xc.__version__ == '4.13.2', 'FIXED_CALENDAR_VERSION_REQUIRED')
    cal = xc.get_calendar('XNYS', start='2015-12-01', end='2025-12-31')
    calendar = []
    for day in cal.sessions:
        close = cal.session_close(day).to_pydatetime().astimezone(NY)-timedelta(minutes=1)
        calendar.append((day.date().isoformat(), close.strftime('%H:%M')))
    calendar_map = dict(calendar)
    calendar_hash = hashlib.sha256(json.dumps(calendar, separators=(',', ':')).encode()).hexdigest()
    source = Path(source)
    manifest = json.loads((source/'manifest.json').read_text())
    require(manifest.get('complete') is True and manifest['symbol'] == 'SOXL' and
            manifest['feed'] == 'sip' and manifest['adjustment'] == 'split', 'WRONG_OR_INCOMPLETE_CAPTURE')
    require(manifest['request'] == dict(timeframe='1Min', start='2015-12-01T00:00:00Z',
            end='2026-01-01T00:00:00Z', limit=10000, adjustment='split', feed='sip', sort='asc'),
            'FIXED_SOURCE_REQUEST_REQUIRED')
    minutes = {}
    count = retained = off_calendar = 0
    previous = None
    page_hashes = []
    for page in manifest['pages']:
        raw = gzip.decompress((source/page['file']).read_bytes())
        require(hashlib.sha256(raw).hexdigest() == page['raw_sha256'], 'SOURCE_PAGE_HASH_MISMATCH')
        obj = json.loads(raw)
        require(obj['symbol'] == 'SOXL' and len(obj['bars']) == page['bars'], 'INVALID_SOURCE_PAGE')
        page_hashes.append(page['raw_sha256'])
        for bar in obj['bars']:
            stamp = datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
            require(stamp.tzinfo is not None and stamp.second == 0 and stamp.microsecond == 0,
                    'NON_MINUTE_OR_NAIVE_TIMESTAMP')
            require(previous is None or stamp > previous, 'DUPLICATE_OR_UNSORTED_BAR')
            # Provider end is inclusive: 2026-01-01T00:00Z is still Dec 31 in NY.
            require(datetime.fromisoformat('2015-12-01T00:00:00+00:00') <= stamp <=
                    datetime.fromisoformat('2026-01-01T00:00:00+00:00') and
                    stamp.astimezone(NY).date().isoformat() < '2026-01-01',
                    'SOURCE_DATE_OUTSIDE_PROTOCOL')
            previous = stamp
            count += 1
            local = stamp.astimezone(NY)
            day, clock = local.date().isoformat(), local.strftime('%H:%M')
            if day not in calendar_map:
                off_calendar += 1
                continue
            if '09:30' <= clock <= '10:00' or clock == calendar_map[day]:
                minutes.setdefault(day, {})[clock] = bar
                retained += 1
    obj = json.loads(Path(secondary).read_bytes())['chart']['result'][0]
    require(obj['meta']['symbol'] == 'SOXL', 'WRONG_SECONDARY_SYMBOL')
    ex_dates = {datetime.fromtimestamp(v['date'], NY).date().isoformat()
                for v in obj.get('events', {}).get('dividends', {}).values()}
    daily = {}
    q = obj['indicators']['quote'][0]
    for i, stamp in enumerate(obj['timestamp']):
        d = datetime.fromtimestamp(stamp, NY).date().isoformat()
        require(d < '2026-01-01', 'SECONDARY_RESERVED_YEAR_LEAK')
        daily[d] = dict(open=q['open'][i], close=q['close'][i])
    sessions, exclusions = assemble(calendar, minutes, ex_dates)
    compare = []
    for r in sessions:
        a, p = daily.get(r['date']), daily.get(r['previous_date'])
        if a and p and a['open'] and p['close']:
            yg = a['open']/p['close']-1
            r['secondary_gap'] = yg
            compare.append(dict(date=r['date'], gap_difference_bps=(r['gap']-yg)*10000,
                                sign_agrees=(r['gap'] < 0) == (yg < 0)))
    quality = dict(calendar='XNYS:4.13.2', calendar_sha256=calendar_hash,
         expected_evaluation_sessions=sum('2016-01-01' <= d <= '2025-12-31' for d, _ in calendar),
         valid_sessions=len(sessions), excluded_sessions=exclusions,
         raw_bars=count, retained_bars=retained, off_calendar_bars=off_calendar,
         source_manifest_sha256=sha(source/'manifest.json'),
         source_page_count=len(page_hashes), source_raw_page_sha256=page_hashes,
         secondary_sha256=sha(secondary), ex_dividend_valid_sessions=sum(r['ex_dividend'] for r in sessions),
         secondary_comparison=dict(paired_sessions=len(compare),
             sign_disagreements=sum(not r['sign_agrees'] for r in compare),
             abs_gap_difference_over_50bps=sum(abs(r['gap_difference_bps']) > 50 for r in compare),
             maximum_abs_gap_difference_bps=max(abs(r['gap_difference_bps']) for r in compare),
             largest_differences=sorted(compare, key=lambda r: abs(r['gap_difference_bps']), reverse=True)[:10]),
         caveats=['SIP revised trade bars, not LSEG midquotes or original real-time arrivals',
                  'Previous close is final regular minute close, excluding close-auction prints timestamped at session close',
                  'Split adjusted price gap includes ex-dividend price effects; separate sensitivity removes those dates',
                  'Valid-session common sample only; no filled-forward prices or calendar-gap bridging'])
    return sessions, quality


def run(source, secondary, output):
    protocol_path = Path('docs/research/soxl-reversal/protocol.json')
    protocol = json.loads(protocol_path.read_text())
    require(protocol['contract'] == 'SOXL_OVERNIGHT_REVERSAL_EXPLORATION:1' and
            protocol['symbol'] == 'SOXL' and protocol['arms'] == list(ARMS) and
            protocol['cost_bps_per_fill'] == [0, 2, 5, 10] and
            protocol['bootstrap'] == dict(replicates=2000, block_sessions=20, seed=5807282) and
            protocol['actual_orders_authorized'] is False, 'FIXED_PROTOCOL_REQUIRED')
    sessions, quality = prepare(source, secondary)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'sessions.json').write_text(json.dumps(sessions, indent=2)+'\n')
    cases, primary_ledgers = {}, {}
    for entry in ENTRIES:
        for bps in protocol['cost_bps_per_fill']:
            key = f'{entry}_{bps}bps'
            cases[key] = {}
            for arm in ARMS:
                result = simulate(sessions, arm=arm, entry=entry, bps=bps)
                cases[key][arm] = result['summary']
                if entry == '09:32' and bps == 5:
                    primary_ledgers[arm] = result['ledger']
                    (output/f'{arm}-daily.json').write_text(json.dumps(result['ledger'], indent=2)+'\n')
    primary = {}
    for arm, ledger in primary_ledgers.items():
        no_div = [r for r in ledger if not r['ex_dividend']]
        primary[arm] = dict(summary=summarize(ledger), by_year_and_partition=groups(ledger),
             excluding_ex_dividend=summarize(no_div),
             intervals=block_intervals(ledger, primary_ledgers['ALWAYS_LONG']),
             gap_buckets=diagnostic_buckets(ledger),
             break_even_adverse_bps_per_side=break_even_bps(sessions, arm=arm))
    # Prior-session volatility is pre-entry, unlike the paper's same-half-hour conditioning.
    available = [r['previous_20_session_vol'] for r in primary_ledgers['GAP_DOWN_LONG']
                 if r['previous_20_session_vol'] is not None]
    median = statistics.median(available)
    vol_groups = {}
    for name, predicate in [('BELOW_POOLED_MEDIAN', lambda v: v < median),
                            ('AT_OR_ABOVE_POOLED_MEDIAN', lambda v: v >= median)]:
        selected = [r for r in primary_ledgers['GAP_DOWN_LONG']
                    if r['previous_20_session_vol'] is not None and predicate(r['previous_20_session_vol'])]
        vol_groups[name] = summarize(selected)
    secondary_sessions = [dict(row, gap=row['secondary_gap']) for row in sessions if 'secondary_gap' in row]
    secondary_sensitivity = {arm: simulate(secondary_sessions, arm=arm)['summary'] for arm in ARMS}
    report = dict(status='COMPLETE_FIXED_RULE_RETROSPECTIVE_SOXL_TRANSFER_TEST',
        protocol_sha256=sha(protocol_path), engine_sha256=sha('research/orb-diagnostics/soxl_reversal.py'),
        runner_sha256=sha(__file__), data_quality=quality, primary_entry='09:32', primary_cost_bps_per_fill=5,
        allocation=.25, cases=cases, primary=primary,
        regression_full=regression(sessions),
        regression_partitions={name: regression([r for r in sessions if lo <= int(r['date'][:4]) <= hi])
             for name, (lo, hi) in dict(EARLY=(2016, 2020), MIDDLE=(2021, 2023), LATE=(2024, 2025)).items()},
        previous_volatility_diagnostic=dict(pooled_median=median, groups=vol_groups,
             note='Descriptive full-sample grouping only, NOT a historical entry filter; cannot use future pooled median operationally'),
        secondary_gap_sign_sensitivity=dict(results=secondary_sensitivity,
             note='Data-quality sensitivity: Yahoo daily gap sign with unchanged SIP intraday entry/exit proxies; not a second executable feed or new strategy'),
        exact_paper_replication=False, independent_confirmation=False,
        fees_are_scenarios=True, short_locate_borrow_cost_and_fillability_unknown=True,
        executable_quote_evidence=False, actual_paper_orders=0, actual_live_orders=0,
        artifact_sha256={p.name: sha(p) for p in sorted(output.iterdir())})
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps(dict(coverage={k: v for k, v in quality.items() if k in
           ('expected_evaluation_sessions', 'valid_sessions', 'ex_dividend_valid_sessions', 'secondary_comparison')},
           primary={a: v['summary'] for a, v in primary.items()}, regression=report['regression_full']), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--secondary', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    run(args.source, args.secondary, args.output)
