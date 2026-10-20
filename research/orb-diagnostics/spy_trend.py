"""Fixed monthly ten-month total-return SMA exploration; no broker transport."""
from bisect import bisect_left
from math import isfinite

from paper_intents import require
from spy_accumulation import xirr


def monthly_targets(rows,month_end_dates):
    """Known calendar closes only. SMA includes current month; equality retains.

    Targets become available only AFTER that close, not at same-day open.
    Month-end dates come from the calendar, never inferred from truncated prices.
    """
    prices=[];target=False;signals={}
    for row in rows:
        if row['date'] not in month_end_dates:continue
        prices.append(row['adjclose'])
        if len(prices)<10:continue
        sma=sum(prices[-10:])/10
        if prices[-1]>sma:target=True
        elif prices[-1]<sma:target=False
        signals[row['date']]=dict(long=target,month_close=prices[-1],sma10=sma)
    return signals


def recovery_stats(ledger):
    require(bool(ledger),'LEDGER_REQUIRED')
    peak=1.;peak_day=ledger[0]['date'];active=None;episodes=[]
    for row in ledger:
        nav=row['unit_nav'];day=row['date']
        if nav>=peak:
            if active:
                active.update(through=day,recovered=True);episodes.append(active);active=None
            peak=nav;peak_day=day
        else:
            if active is None:active=dict(peak_date=peak_day,trough_drawdown=0.)
            active['trough_drawdown']=max(active['trough_drawdown'],1-nav/peak)
    if active:
        active.update(through=ledger[-1]['date'],recovered=False);episodes.append(active)
    from datetime import date
    for e in episodes:e['calendar_days']=(date.fromisoformat(e['through'])-date.fromisoformat(e['peak_date'])).days
    return dict(max_underwater_calendar_days=max((e['calendar_days'] for e in episodes),default=0),
        longest_completed_recovery_calendar_days=max((e['calendar_days'] for e in episodes if e['recovered']),default=0),
        unrecovered_at_end=bool(episodes and not episodes[-1]['recovered']),
        longest_episodes=sorted(episodes,key=lambda e:e['calendar_days'],reverse=True)[:5])


def simulate_trend(rows,*,start,end,arm,cash_mode,rates,month_end_dates,cost_bps=0):
    require(arm in ('HOLD','SMA10') and cash_mode in ('ZERO','TREASURY_PROXY'),'EXPLICIT_TREND_MODE_REQUIRED')
    require(type(cost_bps) in (int,float) and isfinite(cost_bps) and 0<=cost_bps<=100,'INVALID_FRICTION')
    require(all(a['date']<b['date'] for a,b in zip(rows,rows[1:])),'ORDERED_PRICE_SESSIONS_REQUIRED')
    require(all(all(type(r[n]) in (int,float) and isfinite(r[n]) and r[n]>0
                    for n in ('open','close','adjclose')) for r in rows),'POSITIVE_FINITE_PRICES_REQUIRED')
    signals=monthly_targets(rows,month_end_dates);signal_dates=sorted(signals)
    selected=[i for i,r in enumerate(rows) if start<=r['date']<=end]
    require(selected and bisect_left(signal_dates,rows[selected[0]]['date'])>0,'TEN_COMPLETE_MONTHS_REQUIRED')
    rate_dates=[d for d,_ in rates]
    if cash_mode=='TREASURY_PROXY':
        require(rate_dates and all(a<b for a,b in zip(rate_dates,rate_dates[1:])),'ORDERED_CASH_RATES_REQUIRED')
    cash=shares=units=contributed=interest=friction=0.;peak=1.;mdd=0.;weights=0.
    month=None;buys=sells=switches=0;old_target=None;ledger=[];flows=[];fills=[]
    for i in selected:
        r=rows[i];day=r['date'];prior=rows[i-1]['date']
        factor=r['adjclose']/r['close'];adjopen=r['open']*factor
        if cash_mode=='TREASURY_PROXY' and cash:
            k=bisect_left(rate_dates,prior)-1
            require(k>=0 and (prior-rate_dates[k]).days<=14,'CASH_RATE_GAP')
            rate=rates[k][1];require(isfinite(rate) and -.05<=rate<=.30,'CASH_RATE_RANGE')
            earned=cash*rate*(day-prior).days/365;cash+=earned;interest+=earned
        key=(day.year,day.month);monthly=key!=month
        if monthly:month=key
        deposit=10000. if i==selected[0] else (1000. if monthly else 0.)
        if deposit:
            before=shares*adjopen+cash
            units+=deposit if not units else deposit/(before/units)
            cash+=deposit;contributed+=deposit;flows.append((day,-deposit))
        # Strict < day makes a month-end closing signal unusable that morning.
        signal_day=signal_dates[bisect_left(signal_dates,day)-1]
        target=True if arm=='HOLD' else signals[signal_day]['long']
        if old_target is not None and target!=old_target:switches+=1
        old_target=target
        if target and cash>1e-8:
            budget=cash;bought=budget/(adjopen*(1+cost_bps/10000))
            cost=budget-bought*adjopen;friction+=cost;shares+=bought;cash=0.;buys+=1
            fills.append(dict(date=day.isoformat(),side='buy',reference_notional=bought*adjopen,
                              friction=cost,signal_date=signal_day.isoformat()))
        elif not target and shares>0:
            notional=shares*adjopen;cost=notional*cost_bps/10000
            cash+=notional-cost;friction+=cost;shares=0.;sells+=1
            fills.append(dict(date=day.isoformat(),side='sell',reference_notional=notional,
                              friction=cost,signal_date=signal_day.isoformat()))
        total=shares*r['adjclose']+cash;nav=total/units
        peak=max(peak,nav);mdd=max(mdd,1-nav/peak);weights+=cash/total
        ledger.append(dict(date=day.isoformat(),deposit=deposit,contributed=contributed,total=total,cash=cash,
            unit_nav=nav,synthetic_adjusted_units=shares,target_long=target,signal_date=signal_day.isoformat()))
    final=ledger[-1];flows.append((rows[selected[-1]]['date'],final['total']))
    years=((rows[selected[-1]]['date']-rows[selected[0]]['date']).days+1)/365.25
    annual={};prior_nav=1.
    for year in sorted({r['date'][:4] for r in ledger}):
        last=[r for r in ledger if r['date'].startswith(year)][-1]['unit_nav']
        annual[year]=last/prior_nav-1;prior_nav=last
    result=dict(arm=arm,cash_mode=cash_mode,cost_bps=cost_bps,sessions=len(ledger),
        total_contributed=contributed,final_wealth=final['total'],gain_over_contributions=final['total']-contributed,
        money_weighted_annual_return=xirr(flows),time_weighted_total_return=final['unit_nav']-1,
        time_weighted_annual_return=final['unit_nav']**(1/years)-1,unitized_close_max_drawdown=mdd,
        average_cash_weight=weights/len(ledger),final_cash=cash,modeled_cash_interest=interest,
        modeled_trading_friction=friction,buy_days=buys,sell_days=sells,allocation_switches=switches,
        annual_unit_nav_returns=annual,recovery=recovery_stats(ledger),ledger=ledger,fills=fills)
    return result
