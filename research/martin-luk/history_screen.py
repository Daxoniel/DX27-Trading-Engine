"""Price-only necessary-condition prefilter for frozen MLP1.

Provider daily volume is an upper bound, not RTH volume. Do not use this output
as final watchlists: final scan must use regular-session aggregation and volume.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import timedelta
import math
from statistics import mean

from strategy import Rules, ema, scan, stamp


def split_adjust(rows, day, splits):
    out=[]
    for b in rows:
        factor=1.
        for action in splits:
            if b['t'][:10] < action['ex_date'] <= day:
                factor*=action['new_rate']/action['old_rate']
        if not math.isfinite(factor) or factor<=0:raise ValueError('INVALID_SPLIT_FACTOR')
        out.append(dict(t=b['t'],o=b['o']/factor,h=b['h']/factor,l=b['l']/factor,
            c=b['c']/factor,v=b['v']*factor))
    return out


def necessary(rows, rules=Rules()):
    if len(rows)!=160:return 'NO_COMPLETE_160_SESSION_HISTORY'
    cs=[b['c'] for b in rows]
    if not all(math.isfinite(b[k]) and b[k]>0 for b in rows for k in ('o','h','l','c','v')):
        return 'INVALID_SOURCE_VALUES'
    adr=mean((b['h']-b['l'])/b['c'] for b in rows[-20:])
    upper_volume=mean(b['c']*b['v'] for b in rows[-20:])
    if cs[-1]<rules.min_price or adr<rules.min_adr or upper_volume<rules.min_dollar_volume:
        return 'PRICE_ADR_OR_LIQUIDITY_UPPER_BOUND'
    if max(cs[-1]/cs[-64]-1,cs[-1]/cs[-127]-1)<rules.min_momentum:
        return 'MOMENTUM'
    e9,e21,e50=(ema(cs,n) for n in (9,21,50))
    if not(e9[-1]>e21[-1]>e50[-1] and e21[-1]>e21[-6] and cs[-1]>e21[-1]):
        return 'TREND'
    if min(b['l'] for b in rows[-5:])<=min(b['l'] for b in rows[-10:-5]):return 'STRUCTURE'
    crosses=[i for i in range(1,len(cs)) if cs[i-1]<=e21[i-1] and cs[i]>e21[i]]
    start=crosses[-1] if crosses else len(cs)-20
    if any(rows[i]['l']<=e21[i]*(1+rules.support_tolerance) for i in range(start+1,len(cs))):
        return 'PRIOR_PULLBACK_EPISODE'
    return 'NEEDS_RTH_HISTORY'


def normalize_rth(raw, schedule):
    """Return session dictionaries, gaps, and raw RTH bars; no synthetic bars."""
    grouped=defaultdict(dict)
    openings={s['date']:stamp(s['open']) for s in schedule}
    closings={s['date']:stamp(s['close']) for s in schedule}
    for b in raw:
        t=stamp(b['t']);d=b['t'][:10]
        if d not in openings or not openings[d]<=t<closings[d]:continue
        if t in grouped[d]:raise ValueError('DUPLICATE_RTH_BAR')
        if (t-openings[d]).total_seconds()%300:raise ValueError('MISALIGNED_RTH_BAR')
        grouped[d][t]=b
    days={};coverage={}
    for s in schedule:
        d=s['date'];op,cl=openings[d],closings[d]
        expected=int((cl-op).total_seconds()/300)
        rows=sorted(grouped[d].items())
        coverage[d]=dict(expected=expected,observed=len(rows),complete=len(rows)==expected)
        days[d]=[]
        for t,b in rows:
            end=t+timedelta(minutes=5)
            days[d].append(dict(start=t.isoformat(),end=end.isoformat(),
                available_at=(end+timedelta(seconds=1)).isoformat(),
                open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v']))
    return days,coverage


def aggregate(rows):
    if not rows:raise ValueError('EMPTY_RTH_SESSION')
    return dict(t=rows[0]['start'],o=rows[0]['open'],h=max(b['high'] for b in rows),
        l=min(b['low'] for b in rows),c=rows[-1]['close'],v=sum(b['volume'] for b in rows))


def final_plan(day, previous_schedule, day_schedule, metadata, regular_daily, splits):
    """Authoritative frozen scan using exact RTH data for all prefilter survivors.

    All other cohort symbols must have a recorded necessary-condition rejection.
    Reject a candidate on already-observed warmup gaps, not on future test bars.
    """
    assets=[];excluded=[]
    asof=stamp(day_schedule['open'])-timedelta(minutes=30)
    for m in metadata:
        symbol=m['symbol'];raw=[]
        for s in previous_schedule:
            b=regular_daily[symbol].get(s['date'])
            if b is None or not b['complete']:
                excluded.append(dict(symbol=symbol,reason='INCOMPLETE_OBSERVED_RTH_WARMUP',session=s['date']))
                break
            raw.append(b)
        else:
            adjusted=split_adjust(raw,day,splits.get(symbol,[]))
            normalized=[dict(start=s['open'],end=s['close'],
                available_at=(stamp(s['close'])+timedelta(seconds=1)).isoformat(),
                open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v'])
                for s,b in zip(previous_schedule,adjusted)]
            assets.append(dict(symbol=symbol,sector=m['sector'],kind='US_COMMON_STOCK',
                tradable=True,known_at='2025-04-25T20:19:02Z',daily=normalized))
    snapshot=dict(asof=asof.isoformat(),session_open=day_schedule['open'],
        session_close=day_schedule['close'],previous_session_close=previous_schedule[-1]['close'],
        universe_kind='DIAGNOSTIC_SURVIVOR_BIASED',price_basis='ASOF_SPLIT_ADJUSTED',
        adjustment_asof=asof.isoformat(),history_schedule=[(s['open'],s['close']) for s in previous_schedule],assets=assets)
    return scan(snapshot),excluded
