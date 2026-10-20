"""Aggregate private replay ledgers into public-safe diagnostic statistics."""
from collections import Counter, defaultdict
from datetime import datetime
import math
from statistics import mean, median


def trade_statistics(closed, fills, cohort):
    final = {f['trade_id']:f for f in fills if f['side']=='sell'}
    groups = defaultdict(lambda:dict(trades=0,wins=0,pnl=0.))
    losses = streak = 0
    durations = []
    for t in closed:
        losses = losses+1 if t['pnl']<=0 else 0
        streak = max(streak,losses)
        durations.append((datetime.fromisoformat(t['exit_at'])-datetime.fromisoformat(t['entry_at'])).total_seconds()/86400)
        key = cohort[t['symbol']]['sector']
        groups[key]['trades']+=1;groups[key]['wins']+=t['pnl']>0;groups[key]['pnl']+=t['pnl']
    pnl = [t['pnl'] for t in closed]
    return dict(closed_trades=len(closed),mean_closed_trade_pnl=mean(pnl) if pnl else None,
        median_closed_trade_pnl=median(pnl) if pnl else None,
        mean_holding_calendar_days=mean(durations) if durations else None,
        max_consecutive_nonpositive_closed_trades=streak,
        final_exit_reasons=dict(Counter(final[t['trade_id']]['reason'] for t in closed)),
        sectors=dict(groups),
        gross_closed_winners=sum(max(x,0) for x in pnl),gross_closed_losers=-sum(min(x,0) for x in pnl),
        best_closed_trade_pnl=max(pnl) if pnl else None,worst_closed_trade_pnl=min(pnl) if pnl else None)


def monthly_nav(nav, initial=100000):
    months = {}
    for n in nav: months[n['at'][:7]] = n['equity']
    previous = initial;out = []
    for month,equity in sorted(months.items()):
        out.append(dict(month=month,ending_equity=equity,return_since_prior_observed_month=equity/previous-1))
        previous=equity
    return out


def benchmark(first_bar,last_bar,actions,initial=100000,bps=5):
    """One cash-funded SPY purchase; dividends held in cash, final close marked."""
    entry=first_bar['open']*(1+bps/10000);q=math.floor(initial/entry)
    cash=initial-q*entry;receivables=0.;dividends=0.
    start,end=first_bar['start'][:10],last_bar['end'][:10]
    for a in actions:
        if not start<=a['date']<=end: continue
        if a['kind']!='cash_dividend':raise ValueError('UNRESOLVED_BENCHMARK_ACTION')
        amount=q*a['rate'];dividends+=amount
        if a['payable_date']<=end:cash+=amount
        else:receivables+=amount
    equity=cash+q*last_bar['close']+receivables
    return dict(name='SPY_CASH_FUNDED_BUY_HOLD_NO_DIVIDEND_REINVESTMENT',
        start=start,end=end,quantity=q,terminal_equity=equity,net_return=equity/initial-1,
        dividend_income=dividends,receivables=receivables,adverse_entry_bps=bps,
        terminal_sale=False,explicit_broker_fees_verified=False)
