"""Descriptive accounting of sealed, already exposed ORB artifacts; no strategy replay."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

D = Decimal
TOL = D('0.000001')
REPORTS = {'A': 'eb0fe643a1fdf59e97d4f6d53119004b9ad3f6a7df8a42f614ff5425ddeb4e59',
           'B': 'd675aa4ffded773ee9da240cc86e4a1fa22406d6e9b8aa0688441899f5f7abed'}
EXPECTED = {'A': (251, '2025-07-01', '2026-06-30'), 'B': (64, '2026-07-01', '2026-09-30')}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'DUPLICATE_JSON_KEY')
            out[k] = v
        return out
    def invalid(_):
        raise ValueError('NONFINITE_JSON')
    return json.loads(Path(path).read_bytes(), parse_float=D, parse_constant=invalid, object_pairs_hook=pairs)


def number(value):
    require(not isinstance(value, bool) and isinstance(value, (int, D)), 'INVALID_NUMBER')
    value = D(value)
    require(value.is_finite(), 'NONFINITE_NUMBER')
    return value


def close(a, b):
    require(abs(number(a)-number(b)) <= TOL, 'ACCOUNTING_MISMATCH')


def timestamp(value):
    t = datetime.fromisoformat(value)
    require(t.tzinfo is not None and t.utcoffset() is not None, 'NAIVE_TIME')
    return t


def reconstruct(entry, exit_, profile):
    q = number(entry['quantity'])
    require(q > 0 and q == number(exit_['quantity']), 'FILL_QUANTITY')
    require(entry['side'] in ('buy', 'sell') and exit_['side'] in ('buy', 'sell')
            and entry['side'] != exit_['side'], 'FILL_SIDE')
    require(entry['reason'] == 'ENTRY' and exit_['reason'] != 'ENTRY', 'FILL_REASON')
    require(timestamp(entry['at']) <= timestamp(exit_['at']), 'FILL_CLOCK')
    sign = 1 if entry['side'] == 'buy' else -1
    gross = sign*q*(number(exit_['reference'])-number(entry['reference']))
    cash = D(0)
    costs = {k: D(0) for k in ('commission', 'spread_cost', 'slippage_cost')}
    turnover, minimum_hits = D(0), 0
    for f in (entry, exit_):
        ref, price = number(f['reference']), number(f['price'])
        require(ref > 0 and price > 0, 'FILL_PRICE')
        signed = q if f['side'] == 'buy' else -q
        close(f['cash_delta'], -signed*price-number(f['commission']))
        for k in costs:
            require(number(f[k]) >= 0, 'NEGATIVE_COST')
            costs[k] += number(f[k])
        close(abs(price-ref)*q, number(f['spread_cost'])+number(f['slippage_cost']))
        require((price-ref)*signed >= -TOL, 'FAVORABLE_MODELED_COST')
        expected_fee = q*D('0.0005') if profile == 'R0' else max(D('.35'), q*D('.0035'))
        close(f['commission'], expected_fee)
        minimum_hits += profile == 'R1' and number(f['commission']) == D('.35')
        turnover += q*ref
        cash += number(f['cash_delta'])
    close(gross-sum(costs.values()), cash)
    return dict(direction='long' if sign == 1 else 'short', exit_reason=exit_['reason'],
                gross_pnl=gross, net_pnl=cash, reference_turnover=turnover,
                minimum_commission_fills=minimum_hits, **costs)


def aggregate(rows):
    n = len(rows)
    sums = {k: sum((r[k] for r in rows), D(0)) for k in
            ('gross_pnl', 'net_pnl', 'commission', 'spread_cost', 'slippage_cost', 'reference_turnover')}
    cost = sums['commission']+sums['spread_cost']+sums['slippage_cost']
    return dict(trades=n, **sums, total_cost=cost,
                gross_winners=sum(r['gross_pnl'] > 0 for r in rows),
                net_winners=sum(r['net_pnl'] > 0 for r in rows),
                gross_positive_net_nonpositive=sum(r['gross_pnl'] > 0 and r['net_pnl'] <= 0 for r in rows),
                mean_gross_pnl=sums['gross_pnl']/n if n else None,
                mean_net_pnl=sums['net_pnl']/n if n else None,
                modeled_cost_bps=cost/sums['reference_turnover']*10000 if sums['reference_turnover'] else None,
                minimum_commission_fills=sum(r['minimum_commission_fills'] for r in rows))


def diagnose(stage, folder, public):
    folder, public = Path(folder), Path(public)
    for name in ('completion.json', 'report.json'):
        require((folder/name).read_bytes() == (public/name).read_bytes(), 'PUBLIC_ARTIFACT_MISMATCH')
    require(hashlib.sha256((folder/'report.json').read_bytes()).hexdigest() == REPORTS[stage], 'REPORT_HASH')
    manifest = load(folder/'completion.json')['artifact_sha256']
    require(len(manifest) == 22, 'MANIFEST_COUNT')
    for name, digest in manifest.items():
        require(Path(name).name == name, 'MANIFEST_PATH')
        require(hashlib.sha256((folder/name).read_bytes()).hexdigest() == digest, 'ARTIFACT_HASH')
    report = load(folder/'report.json')
    require(report['stage'] == stage and report['integrity_complete'] is True
            and report['status'] == 'COMPLETE_REGISTERED_HISTORICAL_ANALYSIS', 'INCOMPLETE_STUDY')
    arms, by_arm, sessions = {}, {}, None
    for profile in ('R0', 'R1'):
        summary, daily, fills, trades, decisions = [load(folder/f'{profile}-{k}.json') for k in
                                                   ('summary', 'daily', 'fills', 'trades', 'decisions')]
        days = [r['session'] for r in daily]
        n, first, last = EXPECTED[stage]
        require(len(days) == n and days == sorted(set(days)) and days[0] == first and days[-1] == last,
                'DAILY_COVERAGE')
        require(days == [d['session'] for d in report['paired_daily']], 'REPORT_CALENDAR')
        require(sessions is None or days == sessions, 'PROFILE_CALENDAR')
        sessions = days
        fday, tday, dday = defaultdict(list), {}, defaultdict(set)
        for f in fills:
            require(f['session'] in days, 'FILL_SESSION')
            fday[f['session']].append(f)
        for t in trades:
            require(t['session'] in days and t['session'] not in tday, 'TRADE_SESSION')
            tday[t['session']] = t
        for d in decisions:
            require(d['session'] in days, 'DECISION_SESSION')
            dday[d['session']].add(d['reason'])
        require(set(fday) == set(tday), 'UNPAIRED_TRADES')
        rows, by_day = [], {}
        previous = number(summary['initial_cash'])
        for day in daily:
            session = day['session']
            close(day['starting_equity'], previous)
            require(day['data_complete'] is True and day['open_positions'] == 0, 'INCOMPLETE_DAY')
            if session in fday:
                require(len(fday[session]) == 2, 'FILL_PAIR_COUNT')
                row = reconstruct(*fday[session], profile)
                for k in ('gross_pnl', 'net_pnl', 'commission', 'spread_cost', 'slippage_cost'):
                    close(row[k], tday[session][k])
                rows.append(row)
                by_day[session] = row['direction']
                pnl = row['net_pnl']
            else:
                pnl = D(0)
                by_day[session] = 'flat'
            close(previous+pnl, day['ending_equity'])
            previous = number(day['ending_equity'])
        total = aggregate(rows)
        close(total['net_pnl'], summary['net_pnl'])
        close(previous, summary['ending_equity'])
        for k in ('net_pnl', 'gross_pnl', 'commission', 'spread_cost', 'slippage_cost'):
            close(total[k], report['arms'][profile][k])
        zero = Counter('|'.join(sorted(dday[day])) or 'NO_DECISION_RECORDED'
                       for day in days if by_day[day] == 'flat')
        require(len(rows) == report['arms'][profile]['closed_trades'] and
                sum(zero.values()) == report['arms'][profile]['zero_trade_days'], 'COUNT_MISMATCH')
        arms[profile] = dict(all=total,
            by_direction={d: aggregate([r for r in rows if r['direction'] == d]) for d in ('long', 'short')},
            by_exit={reason: aggregate([r for r in rows if r['exit_reason'] == reason])
                     for reason in sorted({r['exit_reason'] for r in rows})},
            zero_trade_days=dict(sorted(zero.items())),
            decision_event_counts=dict(sorted(Counter(d['reason'] for d in decisions).items())))
        by_arm[profile] = by_day
    paired = Counter(f'R0_{by_arm["R0"][s]}__R1_{by_arm["R1"][s]}' for s in sessions)
    return dict(stage=stage, sessions=len(sessions), verified_artifacts=len(manifest), arms=arms,
                direction_day_pairs=dict(sorted(paired.items())), input_report_sha256=REPORTS[stage])


def serialize(value):
    if isinstance(value, D):
        return float(value)
    raise TypeError(type(value).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    stages = {s: diagnose(s, root/f'work/orb-stage-{s.lower()}/attempt-1',
                         root/f'docs/reports/orb-stage-{s.lower()}') for s in ('A', 'B')}
    result = dict(status='COMPLETE_EXPOSED_ARTIFACT_DIAGNOSTIC', confirmation=False,
                  execution_enabled=False, strategy_replayed=False, new_market_data_downloaded=False,
                  standalone_long_short_backtests=False, stages=stages)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, default=serialize, allow_nan=False, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
