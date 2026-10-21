"""Independent Decimal notional accounting and selected-feature audit.

Shares only the sealed input decoder with study.py, not its score, beta,
allocation, cost solver or return calculations. Does not authenticate sources.
"""
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import covariance,variance,mean


def D(x):return Decimal(str(x))


def check_close(a,b,tolerance=1e-5):
    if abs(D(a)-D(b))>D(tolerance):raise ValueError('INDEPENDENT_VALUE_MISMATCH')


def verify_features(formations,adj,raw,calendar,rules):
    checked=0
    for f in formations:
        day=f['asof'];i=calendar.index(day);window=calendar[i-252:i+1]
        if f['beta_window_end']!=day or f['beta_window_start']!=window[0]:raise ValueError('FEATURE_DATE_FAILED')
        source={r['symbol']:r for r in f['base']}
        for r in f['eligible']:
            symbol=r['symbol'];p=adj[symbol];start,end=r['momentum_start'],r['momentum_end']
            if not start<end<day:raise ValueError('FUTURE_MOMENTUM_ENDPOINT')
            bday=day[:7];year,month=map(int,bday.split('-'));n=year*12+month-1
            expected_start=f'{(n-12)//12:04d}-{(n-12)%12+1:02d}'
            expected_end=f'{(n-1)//12:04d}-{(n-1)%12+1:02d}'
            if start!=max(d for d in calendar if d[:7]==expected_start) or end!=max(d for d in calendar if d[:7]==expected_end):
                raise ValueError('MOMENTUM_ENDPOINT_CONVENTION_FAILED')
            own=p[end]/p[start]-1;check_close(own,r['momentum'],1e-10)
            xs=[p[b]/p[a]-1 for a,b in zip(window,window[1:])]
            ys=[adj['SPY'][b]/adj['SPY'][a]-1 for a,b in zip(window,window[1:])]
            estimate=covariance(xs,ys)/variance(ys);check_close(estimate,r['beta'],1e-10)
            if estimate<rules['beta']['minimum']:raise ValueError('BETA_ELIGIBILITY_FAILED')
            adv=mean(raw[symbol][d][0]*raw[symbol][d][1] for d in window[-20:])
            if adv<rules['eligibility']['raw_20_session_mean_dollar_volume_minimum'] or raw[symbol][day][0]<rules['eligibility']['raw_close_minimum']:
                raise ValueError('LIQUIDITY_ELIGIBILITY_FAILED')
            check_close(adv,r['adv20'],.01)
            peers=[q for s,q in source.items() if s!=symbol and q['sector']==r['sector']]
            if len(peers)!=r['peer_count'] or len(peers)<rules['eligibility']['minimum_other_sector_peers']:
                raise ValueError('PEER_COUNT_FAILED')
            peer=mean(adj[q['symbol']][end]/adj[q['symbol']][start]-1 for q in peers)
            check_close(peer,r['peer_momentum'],1e-10);check_close(own-peer,r['relative'],1e-10);checked+=1
    return checked


def audit_case(path,adj,calendar,formations,rules,manifest_digest,code_seal):
    result=json.loads(Path(path).read_text());summary=result['summary'];mode=summary['mode']
    if mode not in ('ordinary','relative','broad','spy') or summary['bps_each_side'] not in rules['costs_bps_per_side']:
        raise ValueError('UNREGISTERED_CASE')
    if summary['input_manifest_sha256']!=manifest_digest or summary['code_seal']!=code_seal:raise ValueError('RUN_BINDING_FAILED')
    lookup={f['asof']:f for f in formations};events={e['date']:e for e in result['events']}
    if len(events)!=len(result['events']):raise ValueError('DUPLICATE_REBALANCE')
    units={};cash=D(rules['initial_proxy_capital']);peak=cash;dd=D(0);costs=D(0);checks=0
    for n in result['nav']:
        day=n['date'];values={s:q*D(adj[s][day]) for s,q in units.items()};before=cash+sum(values.values())
        if day in events:
            e=events[day];f=lookup[e['formation']]
            if day!=calendar[calendar.index(f['asof'])+2]:raise ValueError('REBALANCE_LAG_FAILED')
            check_close(before,e['before']);check_close(cash,e['old_cash'])
            if set(values)!=set(e['old_values']):raise ValueError('OLD_INVENTORY_FAILED')
            for s,v in values.items():check_close(v,e['old_values'][s])
            w=e['weights']
            if any(v<0 for v in w.values()) or sum(w.values())>1+1e-10:raise ValueError('TARGET_FUNDING_FAILED')
            eligible={r['symbol']:r for r in f['eligible']}
            if mode in ('relative','ordinary'):
                used={};expected=[];score='relative' if mode=='relative' else 'momentum'
                for r in sorted(eligible.values(),key=lambda r:(-r[score],r['symbol'])):
                    if len(expected)==10:break
                    if used.get(r['sector'],0)<2:
                        expected.append(r['symbol']);used[r['sector']]=used.get(r['sector'],0)+1
                if set(w)!=set(expected) or any(abs(v-.1)>1e-12 for v in w.values()):raise ValueError('RANK_OR_SECTOR_CAP_FAILED')
            elif mode=='broad':
                if set(w)!=set(eligible):raise ValueError('BROAD_UNIVERSE_FAILED')
                counts={sector:sum(r['sector']==sector for r in eligible.values()) for sector in {r['sector'] for r in eligible.values()}}
                for s,v in w.items():check_close(v,min(1/len(eligible),.2/counts[eligible[s]['sector']]),1e-12)
            elif w!={'SPY':1.}:raise ValueError('BENCHMARK_FAILED')
            new={s:D(v) for s,v in e['new_values'].items()};cash=D(e['new_cash']);after=cash+sum(new.values())
            if set(new)!=set(w):raise ValueError('NEW_INVENTORY_FAILED')
            for s,v in new.items():check_close(v,D(w[s])*after)
            cost=D(summary['bps_each_side'])/10000*sum(abs(new.get(s,D(0))-values.get(s,D(0))) for s in set(new)|set(values))
            check_close(cost,e['cost']);check_close(after+cost,before)
            if cash<0:raise ValueError('NEGATIVE_CASH')
            units={s:v/D(adj[s][day]) for s,v in new.items()};values=new;costs+=cost;checks+=len(w)+4
        equity=cash+sum(values.values());check_close(equity,n['equity']);check_close(cash,n['cash']);check_close(sum(values.values()),n['gross'])
        peak=max(peak,equity);dd=max(dd,1-equity/peak);checks+=3
    check_close(costs,summary['modeled_cost']);check_close(dd,summary['observed_daily_drawdown'],1e-10)
    if summary['halt']:
        if summary['proxy_return'] is not None:raise ValueError('RETURN_AFTER_HALT')
        halt=summary['halt'];day=halt['date']
        if result['nav'] and day<=result['nav'][-1]['date']:raise ValueError('HALT_CHRONOLOGY_FAILED')
        if halt['code']=='HELD_ADJUSTED_CLOSE_MISSING_OR_INVALID':names=units
        else:
            if day not in {calendar[calendar.index(f['asof'])+2] for f in formations}:raise ValueError('UNEXPECTED_HALT_DATE')
            names=()  # Do not claim independent target-halt justification.
        if halt['code']=='HELD_ADJUSTED_CLOSE_MISSING_OR_INVALID' and all(s in adj and day in adj[s] and math.isfinite(adj[s][day]) and adj[s][day]>0 for s in names):
            raise ValueError('UNJUSTIFIED_HELD_HALT')
    else:
        expected=[d for d in calendar if rules['formation_start']<=d<=rules['mark_end']]
        if [n['date'] for n in result['nav']]!=expected:raise ValueError('INCOMPLETE_NAV')
        dates=[calendar[calendar.index(f['asof'])+2] for f in formations]
        if list(events)!=(dates[:1] if mode=='spy' else dates):raise ValueError('MISSING_REBALANCE')
        check_close(summary['proxy_return'],result['nav'][-1]['equity']/rules['initial_proxy_capital']-1,1e-10)
    return dict(status='PASS',checks=checks,rebalance_count=len(events),source_authenticity_verified=False,
        executable_prices_verified=False,broker_accounting_verified=False,promotable=False)
