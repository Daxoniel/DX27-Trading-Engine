"""Post-exposure arithmetic review of delay paths and actual R1 sizing constraints."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
import json
from math import floor
from pathlib import Path
from statistics import median

from fixed_artifacts import diagnose, load, reconstruct, require, close, serialize


def affordable(upper, predicate):
    low, high = 0, max(0, upper)
    while low < high:
        q = (low+high+1)//2
        if predicate(q):
            low = q
        else:
            high = q-1
    return low


def sizing_caps(equity, reference, stop, previous_volume):
    require(equity > 0 and reference > stop > 0 and previous_volume >= 0, 'INVALID_SIZE_INPUT')
    entry, stop_fill = reference*1.0002, stop*.9998
    fee = lambda q: max(.35, q*.0035)
    risk = lambda q: q*(entry-stop_fill)+2*fee(q)
    cash = affordable(floor(equity/entry), lambda q: q*entry+fee(q) <= equity)
    risk_cap = affordable(floor(equity*.0025/(entry-stop_fill)), lambda q: risk(q) <= equity*.0025)
    caps = dict(cash=cash, nominal=floor(equity*.25/entry), volume=floor(previous_volume*.01), risk=risk_cap)
    quantity = min(caps.values())
    require(quantity > 0, 'NO_POSITIVE_SIZE')
    return dict(quantity=quantity, caps=caps, binding=sorted(k for k,v in caps.items() if v == quantity),
                planned_risk_pct=100*risk(quantity)/equity, nominal_pct=100*quantity*entry/equity)


def pairs(fills):
    result = defaultdict(list)
    for f in fills:
        result[f['session']].append(f)
    for v in result.values():
        require(len(v) == 2, 'FILL_PAIR_COUNT')
        reconstruct(*v, 'R0')
    return dict(result)


def delay_components(reference, delayed):
    components = {k:D(0) for k in ('entry_price', 'exit_price', 'quantity_and_capital',
                                  'commission', 'removed_reference_trades', 'added_delayed_trades')}
    counts = Counter()
    signed_entry_bps = []
    for day in sorted(set(reference)|set(delayed)):
        a, b = reference.get(day), delayed.get(day)
        if a is None:
            counts['added'] += 1
            components['added_delayed_trades'] += reconstruct(*b, 'R0')['net_pnl']
            continue
        if b is None:
            counts['removed'] += 1
            components['removed_reference_trades'] -= reconstruct(*a, 'R0')['net_pnl']
            continue
        counts['common'] += 1
        require(a[0]['side'] == b[0]['side'], 'DIRECTION_CHANGED')
        sign = 1 if a[0]['side'] == 'buy' else -1
        q0, q1 = D(a[0]['quantity']), D(b[0]['quantity'])
        i0, i1 = D(a[0]['reference']), D(b[0]['reference'])
        o0, o1 = D(a[1]['reference']), D(b[1]['reference'])
        components['entry_price'] -= q0*sign*(i1-i0)
        components['exit_price'] += q0*sign*(o1-o0)
        components['quantity_and_capital'] += (q1-q0)*sign*(o1-i1)
        components['commission'] -= sum(D(f['commission']) for f in b)-sum(D(f['commission']) for f in a)
        signed_entry_bps.append(sign*(i1-i0)/i0*10000)
        counts['exit_reason_changed'] += a[1]['reason'] != b[1]['reason']
        counts['adverse_entry'] += sign*(i1-i0) > 0
        counts['favorable_entry'] += sign*(i1-i0) < 0
        counts['equal_entry'] += i1 == i0
    actual = sum((reconstruct(*v,'R0')['net_pnl'] for v in delayed.values()),D(0))-sum(
             (reconstruct(*v,'R0')['net_pnl'] for v in reference.values()),D(0))
    close(sum(components.values()), actual)
    return dict(components_usd=components, total_net_delta_usd=actual, counts=dict(sorted(counts.items())),
        common_trade_signed_entry_bps=dict(mean=sum(signed_entry_bps)/len(signed_entry_bps),
                                          median=median(signed_entry_bps)) if signed_entry_bps else None,
        interpretation='EXACT_BASE_QUANTITY_IDENTITY_NOT_UNIQUE_CAUSAL_ATTRIBUTION')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def run(root):
    root=Path(root).resolve()
    contrasts=root/'work/orb-reference-contrasts/attempt-1'
    public=root/'docs/reports/orb-reference-contrasts'
    for n in ('completion.json','report.json'):
        require((contrasts/n).read_bytes()==(public/n).read_bytes(),'CONTRAST_PUBLIC_MISMATCH')
    require(digest(contrasts/'report.json')==load(public/'validation.json')['report_sha256'],'CONTRAST_REPORT_HASH')
    for n,h in load(contrasts/'completion.json')['artifact_sha256'].items():
        require(Path(n).name==n and digest(contrasts/n)==h,'CONTRAST_ARTIFACT_HASH')
    results={}
    for stage in ('A','B'):
        folder=root/f'work/orb-stage-{stage.lower()}/attempt-1'
        diagnose(stage,folder,root/f'docs/reports/orb-stage-{stage.lower()}')
        r=load(folder/'report.json')
        source=root/f'work/orb-stage-{stage.lower()}/stage-{stage.lower()}-with-june-warmup.csv'
        require(digest(source)==r['input']['csv_sha256'],'CSV_HASH')
        require(digest(source.with_suffix('.csv.raw.jsonl'))==r['input']['raw_sha256'],'RAW_HASH')
        fills=load(folder/'R1-fills.json')
        entries=[f for f in fills if f['reason']=='ENTRY']
        need=set()
        for f in entries:
            at=datetime.fromisoformat(f['at'])
            need.update(at-timedelta(minutes=i) for i in (1,2,3,4,5,6))
        bars={}
        with source.open(newline='',encoding='utf-8') as file:
            for row in csv.DictReader(file):
                if row['symbol']=='QQQ':
                    at=datetime.fromisoformat(row['timestamp'])
                    if at in need:
                        require(at not in bars,'DUPLICATE_NEEDED_BAR')
                        bars[at]=row
        require(set(bars)==need,'MISSING_NEEDED_BAR')
        equity={d['session']:float(d['starting_equity']) for d in load(folder/'R1-daily.json')}
        bindings=Counter();single=Counter();risks=[];notionals=[]
        for f in entries:
            at=datetime.fromisoformat(f['at'])
            low=min(float(bars[at-timedelta(minutes=i)]['low']) for i in (2,3,4,5,6))
            previous_volume=float(bars[at-timedelta(minutes=1)]['volume'])
            s=sizing_caps(equity[f['session']],float(f['reference']),low,previous_volume)
            require(s['quantity']==f['quantity'],'ACTUAL_SIZE_MISMATCH')
            close(D(str(float(f['reference'])*1.0002)),f['price'])
            bindings['|'.join(s['binding'])]+=1
            single.update(s['binding']);risks.append(s['planned_risk_pct']);notionals.append(s['nominal_pct'])
        stats=lambda values:dict(min=min(values),median=median(values),mean=sum(values)/len(values),max=max(values))
        a=pairs(load(contrasts/f'{stage}-R0-fills.json'))
        b=pairs(load(contrasts/f'{stage}-DELAY_1M-fills.json'))
        decomp=delay_components(a,b)
        c=load(contrasts/'report.json')['stages'][stage]['arms']
        close(decomp['total_net_delta_usd'],c['DELAY_1M']['metrics']['net_pnl']-c['R0']['metrics']['net_pnl'])
        results[stage]=dict(delay=decomp,r1_sizing=dict(entries_verified=len(entries),
            binding_sets=dict(sorted(bindings.items())),nonexclusive_binding_counts=dict(sorted(single.items())),
            planned_stop_risk_pct=stats(risks),entry_nominal_equity_pct=stats(notionals)),
            original_report_sha256=digest(folder/'report.json'))
    return dict(status='COMPLETE_EXPOSED_CAUSE_ACCOUNTING',confirmation=False,execution_enabled=False,
        strategy_replayed=False,new_market_data_downloaded=False,
        completed_at=datetime.now(timezone.utc).isoformat(),stages=results)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=run(args.root)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(result,f,default=serialize,indent=2,allow_nan=False);f.write('\n')
