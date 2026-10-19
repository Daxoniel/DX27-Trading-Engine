"""Fixed SPY long-hold contribution experiment; no orders or threshold search."""
from bisect import bisect_left
from datetime import date
from math import isfinite

from paper_intents import require

ARMS=('IMMEDIATE','DCA12','DIP5')


def dip_signal(rows,index):
    """At next open index: yesterday close vs preceding 252 session closes.

    Yesterday is excluded from its own high reference. No today's open/close.
    """
    require(index>=253,'FULL_PRIOR_252_SESSION_SIGNAL_HISTORY_REQUIRED')
    peak=max(r['close'] for r in rows[index-253:index-1])
    return rows[index-1]['close']<=peak*.95


def xirr(flows):
    origin=flows[0][0]
    terms=[((d-origin).days/365.25,v) for d,v in flows]
    def npv(rate):return sum(v/(1+rate)**t for t,v in terms)
    lo,hi=-.9999,1.
    while npv(hi)>0 and hi<1024:hi=2*hi+1
    require(npv(lo)>0 and npv(hi)<0,'XIRR_ROOT_NOT_BRACKETED')
    for _ in range(100):
        mid=(lo+hi)/2
        if npv(mid)>0:lo=mid
        else:hi=mid
    return (lo+hi)/2


def simulate(rows,*,start,end,arm,cash_mode,rates=(),cost_bps=0):
    require(arm in ARMS and cash_mode in ('ZERO','TREASURY_PROXY'),'EXPLICIT_ACCUMULATION_MODE_REQUIRED')
    require(type(cost_bps) in (int,float) and isfinite(cost_bps) and 0<=cost_bps<=100,'INVALID_COST_SCENARIO')
    require(all(a['date']<b['date'] for a,b in zip(rows,rows[1:])),'STRICT_ORDERED_SESSIONS_REQUIRED')
    for r in rows:
        require(all(type(r[n]) in (int,float) and isfinite(r[n]) and r[n]>0 for n in ('open','close','adjclose')),
                'FINITE_POSITIVE_PRICES_REQUIRED')
    selected=[i for i,r in enumerate(rows) if start<=r['date']<=end]
    require(selected and selected[0]>=253,'EVALUATION_AND_WARMUP_REQUIRED')
    rate_dates=[r[0] for r in rates]
    if cash_mode=='TREASURY_PROXY':
        require(rates and all(a<b for a,b in zip(rate_dates,rate_dates[1:])),'ORDERED_CASH_RATES_REQUIRED')
    cash=shares=units=contributions=interest=costs=0.;peak=1.;mdd=0.;cash_weight_sum=0.
    month=None;month_index=-1;trades=0;uninvested=0;first_buy=None;ledger=[];flows=[]
    for i in selected:
        row=rows[i];day=row['date'];prior_day=rows[i-1]['date']
        factor=row['adjclose']/row['close'];adjopen=row['open']*factor
        # Previous-session-or-older cash balance accrues calendar days. Rate
        # observation is strictly BEFORE the prior SPY session (one-session lag).
        if cash_mode=='TREASURY_PROXY' and cash:
            k=bisect_left(rate_dates,prior_day)-1
            require(k>=0 and (prior_day-rate_dates[k]).days<=14,'CASH_RATE_GAP')
            rate=rates[k][1]
            require(isfinite(rate) and -.05<=rate<=.30,'INVALID_ANNUAL_CASH_RATE')
            earned=cash*rate*(day-prior_day).days/365
            cash+=earned;interest+=earned
        key=(day.year,day.month);monthly=key!=month
        if monthly:month=key;month_index+=1
        deposit=10000. if i==selected[0] else (1000. if monthly else 0.)
        if deposit:
            before=shares*adjopen+cash
            units+=deposit if not units else deposit/(before/units)
            cash+=deposit;contributions+=deposit;flows.append((day,-deposit))
        budget=0.
        if arm=='IMMEDIATE' and monthly:budget=cash
        elif arm=='DCA12' and monthly:
            budget=min(cash,10000/12+(1000 if month_index else 0)) if month_index<11 else cash
        elif arm=='DIP5' and dip_signal(rows,i):budget=cash
        bought=0.
        if budget>1e-8:
            bought=budget/(adjopen*(1+cost_bps/10000))
            costs+=budget-bought*adjopen;shares+=bought;cash-=budget;trades+=1
            if first_buy is None:first_buy=day.isoformat()
        total=shares*row['adjclose']+cash
        nav=total/units;peak=max(peak,nav);mdd=max(mdd,1-nav/peak)
        cash_weight_sum+=cash/total;uninvested+=cash/total>.99
        ledger.append(dict(date=day.isoformat(),deposit=deposit,contributed=contributions,
            total=total,cash=cash,cash_weight=cash/total,unit_nav=nav,
            synthetic_adjusted_units=shares,bought_adjusted_units=bought))
    final=ledger[-1];flows.append((rows[selected[-1]]['date'],final['total']))
    years=((rows[selected[-1]]['date']-rows[selected[0]]['date']).days+1)/365.25
    return dict(arm=arm,cash_mode=cash_mode,cost_bps=cost_bps,first_session=ledger[0]['date'],
        last_session=ledger[-1]['date'],sessions=len(ledger),total_contributed=contributions,
        final_wealth=final['total'],gain_over_contributions=final['total']-contributions,
        money_weighted_annual_return=xirr(flows),time_weighted_total_return=final['unit_nav']-1,
        time_weighted_annual_return=final['unit_nav']**(1/years)-1,
        unitized_close_max_drawdown=mdd,average_cash_weight=cash_weight_sum/len(ledger),
        final_cash=cash,modeled_cash_interest=interest,modeled_purchase_friction=costs,
        purchase_days=trades,almost_all_cash_sessions=uninvested,first_buy=first_buy,
        ledger=ledger)
