"""Frozen selected-basket risk budget extension. No network or broker calls."""
import argparse
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean, stdev

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sm1_parent', PROJECT / 'research/sector-momentum/study.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def forecast(adj, calendar, asof, weights, rules):
    end = calendar.index(asof)
    count = rules['forecast_return_observations']
    days = calendar[max(0, end-count):end+1]
    if len(days) != count+1:
        raise ValueError('RISK_HISTORY_TOO_SHORT')
    if not weights:
        return 0.
    if any(not parent.positive(adj.get(s, {}).get(d)) for s in weights for d in days):
        raise ValueError('RISK_HISTORY_MISSING')
    returns = [sum(w*(adj[s][b]/adj[s][a]-1) for s, w in weights.items())
               for a, b in zip(days, days[1:])]
    return math.sqrt(rules['annualization_sessions'] * mean(r*r for r in returns))


def scale_for(volatility, rules):
    if not math.isfinite(volatility) or volatility < 0:
        raise ValueError('INVALID_FORECAST')
    return min(rules['maximum_scale'], rules['annual_volatility_target']/volatility) if volatility else 1.


def make_plans(adj, calendar, formations, mode, overlay, original, rules):
    plans = []
    initial_scale = None
    for f in formations:
        base = parent.targets(f, mode, original)
        vol = forecast(adj, calendar, f['asof'], base, rules)
        candidate = scale_for(vol, rules)
        if initial_scale is None:
            initial_scale = candidate
        scale = 1. if overlay == 'unmanaged' else initial_scale if overlay == 'fixed_initial' else candidate
        if overlay not in rules['overlays']:
            raise ValueError('UNKNOWN_OVERLAY')
        plans.append(dict(formation=f['asof'], date=calendar[calendar.index(f['asof'])+2],
            forecast_volatility=vol, scale=scale,
            weights={s: w*scale for s, w in base.items()},
            target_exposure=sum(base.values())*scale,
            target_beta=sum(base.get(r['symbol'], 0)*r['beta'] for r in f['eligible'])*scale))
    return plans


def run(adj, calendar, plans, bps, original):
    units = {}; cash = original['initial_proxy_capital']; events = []; nav = []; halt = None
    schedule = {p['date']: p for p in plans}
    if len(schedule) != len(plans):
        raise ValueError('DUPLICATE_REBALANCE')
    for day in calendar:
        if not original['formation_start'] <= day <= original['mark_end']:
            continue
        if any(not parent.positive(adj.get(s, {}).get(day)) for s in units):
            halt = dict(date=day, code='HELD_CLOSE_MISSING'); break
        values = {s: q*adj[s][day] for s, q in units.items()}
        if day in schedule:
            plan = schedule[day]; weights = plan['weights']
            if any(not parent.positive(adj.get(s, {}).get(day)) for s in weights):
                halt = dict(date=day, code='TARGET_CLOSE_MISSING'); break
            before = cash+sum(values.values())
            new, after_cash, cost = parent.rebalance(values, cash, weights, bps/10000)
            events.append(dict(plan, old_values=values, old_cash=cash, before=before,
                new_values=new, new_cash=after_cash, cost=cost,
                turnover_notional=sum(abs(new.get(s, 0)-values.get(s, 0)) for s in set(new)|set(values))))
            units = {s: v/adj[s][day] for s, v in new.items()}
            cash = after_cash; values = new
        nav.append(dict(date=day, equity=cash+sum(values.values()), cash=cash, gross=sum(values.values())))
    peak = original['initial_proxy_capital']; dd = 0
    for n in nav:
        peak = max(peak, n['equity']); dd = max(dd, 1-n['equity']/peak)
    # First entry has cost only; daily volatility starts at the first holding return.
    holding_daily = [b['equity']/a['equity']-1 for a, b in zip(nav, nav[1:])
                     if a['date'] >= plans[0]['date']]
    intervals = []
    for i, e in enumerate(events):
        end = events[i+1]['date'] if i+1 < len(events) else nav[-1]['date']
        finish = events[i+1]['before'] if i+1 < len(events) else nav[-1]['equity']
        intervals.append(dict(start=e['date'], end=end, return_after_start_cost=finish/e['before']-1))
    return dict(events=events, nav=nav, intervals=intervals, summary=dict(
        status='HALTED' if halt else 'CONDITIONAL_ADJUSTED_CLOSE_PROXY', halt=halt,
        proxy_return=None if halt else nav[-1]['equity']/original['initial_proxy_capital']-1,
        observed_drawdown=dd, modeled_cost=sum(e['cost'] for e in events),
        turnover_over_initial_capital=sum(e['turnover_notional'] for e in events)/original['initial_proxy_capital'],
        mean_daily_observed_exposure=mean(n['gross']/n['equity'] for n in nav),
        mean_formation_target_exposure=mean(p['target_exposure'] for p in plans),
        mean_formation_target_beta=mean(p['target_beta'] for p in plans),
        observed_annualized_daily_volatility=stdev(holding_daily)*math.sqrt(252) if len(holding_daily)>1 else None,
        basket_positive_intervals=sum(i['return_after_start_cost']>0 for i in intervals),
        basket_intervals=len(intervals), rebalance_count=len(events), actual_orders=0,
        independent_out_of_sample=False, promotable=False, executable_prices_verified=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); public = PROJECT/'docs/research/sector-risk'
    rules = json.loads((public/'protocol.json').read_text())
    original_path = PROJECT/'docs/research/sector-momentum/protocol.json'
    assert sha256(original_path.read_bytes()).hexdigest() == rules['parent_protocol_sha256']
    assert sha256((a.source/'input-manifest.json').read_bytes()).hexdigest() == rules['input_manifest_sha256']
    for name, digest in json.loads((public/'code-seal.json').read_text()).items():
        assert sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == digest
    for name, digest in json.loads((original_path.parent/'code-seal.json').read_text()).items():
        assert sha256((PROJECT/'research/sector-momentum'/name).read_bytes()).hexdigest() == digest
    original = json.loads(original_path.read_text())
    adj, raw, cohort, cal, _ = parent.load(a.source/'input-manifest.json', original)
    ends = {d[:7]: d for d in cal if original['formation_start']<=d<=original['formation_end']}
    formations = [parent.features(d, adj, raw, cohort, cal, original) for d in sorted(ends.values())]
    assert formations == json.loads((a.source/'formations.json').read_text())
    a.output.mkdir(parents=True, exist_ok=True)
    from audit import audit_case
    public_runs = {}; validations = {}
    for mode in rules['signals']:
        for overlay in rules['overlays']:
            plans = make_plans(adj, cal, formations, mode, overlay, original, rules)
            for bps in rules['costs_bps_per_side']:
                case = run(adj, cal, plans, bps, original)
                key = f'{mode}-{overlay}-{bps}bp'
                validations[key] = audit_case(case, adj, cal, formations, mode, overlay, bps, original, rules)
                if overlay == 'unmanaged':
                    old = json.loads((a.source/f'{mode}-{bps}bp.json').read_text())
                    assert case['nav'] == old['nav'], 'UNMANAGED_PARENT_NAV_CHANGED'
                    assert case['summary']['proxy_return'] == old['summary']['proxy_return']
                (a.output/(key+'.json')).write_text(json.dumps(case, sort_keys=True)+'\n')
                public_runs[key] = dict(summary=case['summary'], nav=case['nav'], intervals=case['intervals'],
                    risk_plans=[{k: v for k, v in plan.items() if k != 'weights'} for plan in plans])
                print(key, json.dumps(case['summary']), flush=True)
    result = dict(scope=rules['scope'], runs=public_runs, actual_orders=0,
        protocol_sha256=sha256((public/'protocol.json').read_bytes()).hexdigest(),
        input_manifest_sha256=rules['input_manifest_sha256'], independent_audits=validations,
        independent_out_of_sample=False, full_period_broad_control_available=False, promotable=False)
    (a.output/'results.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
