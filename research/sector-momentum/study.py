"""Frozen high-beta ranking study with adjusted-close notional proxies.

No orders, executable closing-price claim or point-in-time certification.
"""
import argparse
from collections import Counter,defaultdict
from datetime import date
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import mean


def shift_month(day,offset):
    n=day.year*12+day.month-1+offset
    return f'{n//12:04d}-{n%12+1:02d}'


def beta(stock,market):
    if len(stock)!=len(market) or len(stock)<2:raise ValueError('ALIGNED_RETURNS_REQUIRED')
    a,b=mean(stock),mean(market);den=sum((x-b)**2 for x in market)
    if den<=0:raise ValueError('ZERO_MARKET_VARIANCE')
    return sum((x-a)*(y-b) for x,y in zip(stock,market))/den


def positive(value):return isinstance(value,(int,float)) and math.isfinite(value) and value>0


def load(manifest_path,protocol):
    path=Path(manifest_path);m=json.loads(path.read_text())
    if m['protocol_sha256']!=sha256(json.dumps(protocol,indent=2).encode()+b'\n').hexdigest():
        raise ValueError('PROTOCOL_BINDING_FAILED')
    old=path.parent.parent/'mlp1-history'
    for name,field in [('cohort.json','cohort_sha256'),('schedule.json','schedule_sha256')]:
        if sha256((old/name).read_bytes()).hexdigest()!=m[field]:raise ValueError('OLD_INPUT_SEAL_FAILED')
    adj={};raw={}
    for kind,dest in [('adjusted',adj),('raw_daily',raw)]:
        for ref in m[kind]:
            blob=gzip.decompress((path.parent/ref['path']).read_bytes())
            if sha256(blob).hexdigest()!=ref['sha256']:raise ValueError('PRICE_SEAL_FAILED')
            for symbol,rows in json.loads(blob).items():
                if symbol in dest:raise ValueError('DUPLICATE_SYMBOL_BATCH')
                if kind=='adjusted':dest[symbol]={r['t'][:10]:r['c'] for r in rows}
                else:dest[symbol]={r['t'][:10]:(r['c'],r['v']) for r in rows}
                if len(dest[symbol])!=len(rows):raise ValueError('DUPLICATE_SYMBOL_DATE')
    cohort=json.loads((old/'cohort.json').read_text());schedule=json.loads((old/'schedule.json').read_text())
    calendar=sorted(adj['SPY'])
    expected=[s['date'] for s in schedule if protocol['formation_start']<=s['date']<=protocol['mark_end']]
    if expected!=[d for d in calendar if protocol['formation_start']<=d<=protocol['mark_end']]:
        raise ValueError('BENCHMARK_CALENDAR_MISMATCH')
    return adj,raw,cohort,calendar,m


def features(asof,adj,raw,cohort,calendar,rules):
    end=calendar.index(asof);days=calendar[end-252:end+1]
    if len(days)!=253:raise ValueError('BENCHMARK_WARMUP_MISSING')
    ends={d[:7]:d for d in calendar if d<=asof}
    start=ends[shift_month(date.fromisoformat(asof),-12)]
    finish=ends[shift_month(date.fromisoformat(asof),-1)]
    bm=[adj['SPY'][b]/adj['SPY'][a]-1 for a,b in zip(days,days[1:])]
    base=[];rejections=Counter()
    for c in cohort:
        symbol=c['symbol'];p=adj.get(symbol,{});r=raw.get(symbol,{})
        need=[start,finish]+days
        if any(not positive(p.get(d)) for d in need):rejections['PAST_ADJUSTED_INPUT_MISSING_OR_INVALID']+=1;continue
        if any(d not in r or not positive(r[d][0]) or not positive(r[d][1]) for d in days[-20:]):
            rejections['PAST_RAW_LIQUIDITY_INPUT_MISSING_OR_INVALID']+=1;continue
        adv=mean(r[d][0]*r[d][1] for d in days[-20:])
        if r[asof][0]<rules['eligibility']['raw_close_minimum'] or adv<rules['eligibility']['raw_20_session_mean_dollar_volume_minimum']:
            rejections['PRICE_OR_LIQUIDITY']+=1;continue
        returns=[p[b]/p[a]-1 for a,b in zip(days,days[1:])]
        base.append(dict(symbol=symbol,sector=c['sector'],beta=beta(returns,bm),momentum=p[finish]/p[start]-1,
            momentum_start=start,momentum_end=finish,asof=asof,raw_close=r[asof][0],adv20=adv))
    groups=defaultdict(list)
    for row in base:groups[row['sector']].append(row)
    eligible=[]
    for row in base:
        peers=groups[row['sector']];n=len(peers)-1
        if n<rules['eligibility']['minimum_other_sector_peers']:rejections['TOO_FEW_PAST_PEERS']+=1;continue
        if row['beta']<rules['beta']['minimum']:rejections['BETA_BELOW_THRESHOLD']+=1;continue
        peer_mean=sum(x['momentum'] for x in peers if x['symbol']!=row['symbol'])/n
        eligible.append(dict(row,peer_count=n,peer_momentum=peer_mean,relative=row['momentum']-peer_mean))
    return dict(asof=asof,base=base,eligible=eligible,rejections=dict(rejections),
        beta_window_start=days[0],beta_window_end=days[-1],beta_observations=252)


def targets(formation,mode,rules):
    rows=formation['eligible'];sectors=Counter();weights={}
    if mode=='spy':return {'SPY':1.}
    if mode=='broad':
        if not rows:return {}
        counts=Counter(r['sector'] for r in rows)
        for r in rows:weights[r['symbol']]=min(1/len(rows),.2/counts[r['sector']])
        return weights
    key='relative' if mode=='relative' else 'momentum'
    for r in sorted(rows,key=lambda r:(-r[key],r['symbol'])):
        if len(weights)==rules['position_count']:break
        if sectors[r['sector']]>=rules['maximum_names_per_sector']:continue
        weights[r['symbol']]=rules['weight_per_slot'];sectors[r['sector']]+=1
    return weights


def rebalance(values,cash,weights,rate):
    if any(w<0 for w in weights.values()) or sum(weights.values())>1+1e-12:
        raise ValueError('UNFUNDED_TARGET')
    before=cash+sum(values.values());names=set(values)|set(weights)
    lo,hi=0.,before
    for _ in range(80):
        after=(lo+hi)/2;turnover=sum(abs(weights.get(s,0)*after-values.get(s,0)) for s in names)
        if after+rate*turnover>before:hi=after
        else:lo=after
    after=(lo+hi)/2;new={s:w*after for s,w in weights.items()}
    cost=rate*sum(abs(new.get(s,0)-values.get(s,0)) for s in names)
    remaining=before-cost-sum(new.values())
    if remaining< -1e-7:raise ValueError('NEGATIVE_CASH')
    return new,max(0.,remaining),cost


def run(adj,calendar,formations,mode,bps,rules):
    units={};cash=rules['initial_proxy_capital'];nav=[];events=[];halt=None;costs=0
    days=[d for d in calendar if rules['formation_start']<=d<=rules['mark_end']]
    entries={calendar[calendar.index(f['asof'])+2]:f for f in formations}
    if any(d<=f['asof'] for d,f in entries.items()):raise ValueError('REBALANCE_LAG_FAILED')
    for day in days:
        if any(not positive(adj.get(s,{}).get(day)) for s in units):
            halt=dict(code='HELD_ADJUSTED_CLOSE_MISSING_OR_INVALID',date=day);break
        values={s:q*adj[s][day] for s,q in units.items()}
        if day in entries and (mode!='spy' or not events):
            f=entries[day];w=targets(f,mode,rules)
            if any(not positive(adj.get(s,{}).get(day)) for s in w):
                halt=dict(code='TARGET_CLOSE_MISSING_OR_INVALID',date=day);break
            before=cash+sum(values.values());new,after_cash,cost=rebalance(values,cash,w,bps/10000)
            events.append(dict(date=day,formation=f['asof'],before=before,old_values=values,old_cash=cash,
                weights=w,new_values=new,new_cash=after_cash,cost=cost,
                ex_ante_weighted_beta=sum(w.get(r['symbol'],0)*r['beta'] for r in f['eligible']) if mode!='spy' else 1.))
            units={s:v/adj[s][day] for s,v in new.items()};cash=after_cash;values=new;costs+=cost
        equity=cash+sum(values.values());nav.append(dict(date=day,equity=equity,cash=cash,gross=sum(values.values())))
    peak=rules['initial_proxy_capital'];dd=0
    for n in nav:peak=max(peak,n['equity']);dd=max(dd,1-n['equity']/peak)
    intervals=[];stock_intervals=[]
    for i,e in enumerate(events):
        end=events[i+1]['date'] if i+1<len(events) else nav[-1]['date']
        if end<=e['date']:continue
        # Mark before the next rebalance's cost; this is a basket interval, not a broker trade.
        value=next((x['before'] for x in events if x['date']==end),nav[-1]['equity'])
        intervals.append(dict(start=e['date'],end=end,return_after_start_cost=value/e['before']-1))
        stock_intervals.extend(adj[s][end]/adj[s][e['date']]-1 for s in e['weights'])
    summary=dict(mode=mode,bps_each_side=bps,status='HALTED' if halt else 'CONDITIONAL_ADJUSTED_CLOSE_PROXY',
        halt=halt,proxy_return=None if halt else nav[-1]['equity']/rules['initial_proxy_capital']-1,
        last_observed_equity=nav[-1]['equity'] if nav else rules['initial_proxy_capital'],
        observed_daily_drawdown=dd,rebalance_count=len(events),modeled_cost=costs,
        positive_basket_intervals=sum(i['return_after_start_cost']>0 for i in intervals),basket_intervals=len(intervals),
        positive_stock_return_intervals=sum(r>0 for r in stock_intervals),stock_return_intervals=len(stock_intervals),
        frequency_note='Repeated-issuer gross source-return intervals, not independent observations or executed trade wins.',
        mean_observed_exposure=mean(n['gross']/n['equity'] for n in nav) if nav else 0,
        actual_orders=0,promotable=False,independent_out_of_sample=False,execution_validated=False)
    return dict(summary=summary,nav=nav,events=events,intervals=intervals)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    project=Path(__file__).resolve().parents[2];protocol_path=project/'docs/research/sector-momentum/protocol.json'
    rules=json.loads(protocol_path.read_text());seal=json.loads((protocol_path.parent/'code-seal.json').read_text())
    for name,digest in seal.items():
        if sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=digest:raise ValueError('CODE_SEAL_FAILED')
    adj,raw,cohort,calendar,manifest=load(a.root/'input-manifest.json',rules)
    ends={d[:7]:d for d in calendar if rules['formation_start']<=d<=rules['formation_end']}
    formations=[features(d,adj,raw,cohort,calendar,rules) for d in sorted(ends.values())]
    (a.root/'formations.json').write_text(json.dumps(formations,sort_keys=True)+'\n')
    for bps in rules['costs_bps_per_side']:
        for mode in ('ordinary','relative','broad','spy'):
            result=run(adj,calendar,formations,mode,bps,rules)
            result['summary'].update(input_manifest_sha256=sha256((a.root/'input-manifest.json').read_bytes()).hexdigest(),code_seal=seal)
            (a.root/(mode+f'-{bps}bp.json')).write_text(json.dumps(result,sort_keys=True)+'\n')
            print(json.dumps(result['summary']),flush=True)


if __name__=='__main__':main()
