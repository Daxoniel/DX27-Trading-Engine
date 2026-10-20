"""Independent raw-window/fresh-reentry audit on top of Decimal quote accounting.

Does not import the signal or replay implementation.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING
import gzip
from hashlib import sha256
import json
from pathlib import Path

from audit_quote_history import audit_quotes


def parse(s):return datetime.fromisoformat(s.replace('Z','+00:00'))


def audit(root,manifest,quotes):
    root,manifest=Path(root),Path(manifest)
    result=audit_quotes(root,quotes)
    read=lambda n:json.loads((root/(n+'.json')).read_text())
    summary,fills,closed,events=(read(n) for n in ('summary','fills','closed','events'))
    if sha256(manifest.read_bytes()).hexdigest()!=summary['input_manifest_sha256']:raise ValueError('MANIFEST_BINDING_FAILED')
    refs={r['path'][:10]:r for r in json.loads(manifest.read_text())['sessions']}
    attempts=defaultdict(list);terminals=defaultdict(list)
    for e in events:
        if e['kind']=='SIGNAL_ATTEMPT':attempts[(e['at'][:10],e['symbol'])].append(e)
        if e['kind'] in ('QUOTE_ENTRY_REJECTED','CAPACITY_REJECTED','ENTRY_EXPIRED'):
            terminals[(e['at'][:10],e['symbol'])].append(parse(e['at']))
    for t in closed:terminals[(t['exit_at'][:10],t['symbol'])].append(parse(t['exit_at']))
    for group in attempts.values():
        if not summary['reentry'] and len(group)>1:raise ValueError('FORBIDDEN_REPEAT_ATTEMPT')
        if [e['attempt_index'] for e in group]!=list(range(1,len(group)+1)):raise ValueError('ATTEMPT_SEQUENCE_FAILED')
    buys=defaultdict(list)
    for f in fills:
        if f['side']=='buy':buys[f['at'][:10]].append(f)
    checked=0;minutes=summary['signal_minutes'];step=timedelta(minutes=minutes)
    for day,entries in buys.items():
        ref=refs[day];raw=gzip.decompress((manifest.parent/ref['path']).read_bytes())
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('SESSION_BINDING_FAILED')
        session=json.loads(raw);plan=session['plan'];opening=parse(plan['session_open'])
        source=session['minute_bars'] if minutes==1 else session['bars']
        indexed={s:{parse(b['end']):b for b in rows} for s,rows in source.items()}
        candidates={c['symbol']:c for c in plan['watchlist']}
        for f in entries:
            at=parse(f['signal_at']);end=at-timedelta(seconds=1)
            if not opening<at<=opening+timedelta(hours=2):raise ValueError('SIGNAL_WINDOW_FAILED')
            window=[indexed[f['symbol']][end-i*step] for i in (2,1,0)]
            if any(parse(b['start'])!=end-(3-i)*step or parse(b['available_at'])>at
                   or b.get('invalid_components') for i,b in enumerate(window)):
                raise ValueError('FUTURE_OR_NONCONTIGUOUS_SIGNAL_WINDOW')
            encoded=json.dumps(window,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            if sha256(encoded).hexdigest()!=f['signal_evidence_sha256']:raise ValueError('SIGNAL_EVIDENCE_SEAL_FAILED')
            key=(day,f['symbol']);previous=[t for t in terminals[key] if t<=at]
            since=max([opening]+previous)
            if parse(window[0]['start'])<since:raise ValueError('REUSED_PREFLAT_OR_FAILED_ORDER_BARS')
            count=sum(parse(e['at'])<=at for e in attempts[key])
            if count!=f['attempt_index']:raise ValueError('FILL_ATTEMPT_INDEX_FAILED')
            c=candidates[f['symbol']];support=c['support_levels'][f['selected_support']]
            stop=min(b['low'] for b in window);last=window[-1];prior_low=min(b['low'] for b in window[:2]);rules=plan['rules']
            if not (support*(1-rules['max_stop'])<=prior_low<=support*(1+rules['support_tolerance'])
                    and last['close']>max(support,window[-2]['high']) and last['close']>last['open']):
                raise ValueError('RECOVERY_TEMPLATE_FAILED')
            limit=(Decimal(str(last['close']))*(1+Decimal(str(summary['adverse_bps_each_side']))/10000)).quantize(Decimal('.01'),rounding=ROUND_CEILING)
            if abs(Decimal(str(f['limit_price']))-limit)>Decimal('.00000001') or f['stop_price']!=stop:
                raise ValueError('SIGNAL_LIMIT_OR_STOP_FAILED')
            distance=(float(limit)-stop)/float(limit)
            if not rules['min_stop']<=distance<=min(rules['max_stop'],c['adr']/2):raise ValueError('STOP_DISTANCE_FAILED')
            if parse(f['at'])!=end+timedelta(minutes=1):raise ValueError('FIRST_LATER_MINUTE_EXECUTION_FAILED')
            checked+=1
    by_id={f['trade_id']:f for f in fills if f['side']=='buy'}
    intervals=defaultdict(list)
    exits={t['trade_id']:t for t in closed}
    for tid,buy in by_id.items():
        intervals[buy['symbol']].append((parse(buy['at']),parse(exits[tid]['exit_at']) if tid in exits else None))
    for group in intervals.values():
        group.sort()
        for previous,current in zip(group,group[1:]):
            if previous[1] is None or current[0]<=previous[1]:raise ValueError('OVERLAPPING_SAME_NAME_HOLDINGS')
    for t in closed:
        b=by_id[t['trade_id']];risk=b['quantity']*(b['price']-b['stop_price'])
        if abs(risk-t['initial_dollar_risk'])>1e-6 or abs(t['pnl']/risk-t['realized_r'])>1e-6:
            raise ValueError('REALIZED_R_ACCOUNTING_FAILED')
    return dict(result,signal_windows_checked=checked,fresh_window_reentry_verified=True,
        first_later_minute_execution_verified=True,no_overlapping_same_name_positions=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--quotes',type=Path,required=True);a=p.parse_args()
    r=audit(a.report,a.manifest,a.quotes)
    (a.report/'factorial-validation.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
