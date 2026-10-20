"""Aggregate private replay ledgers into public-safe diagnostic statistics."""
from collections import Counter, defaultdict
from datetime import datetime
import math
from statistics import mean, median
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from audit_history import audit
from prepare_replay_v2 import normalized_actions


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
    winners = sorted((t for t in closed if t['pnl']>0),key=lambda t:-t['pnl'])
    return dict(closed_trades=len(closed),mean_closed_trade_pnl=mean(pnl) if pnl else None,
        median_closed_trade_pnl=median(pnl) if pnl else None,
        mean_holding_calendar_days=mean(durations) if durations else None,
        max_consecutive_nonpositive_closed_trades=streak,
        final_exit_reasons=dict(Counter(final[t['trade_id']]['reason'] for t in closed)),
        sectors=dict(groups),
        gross_closed_winners=sum(max(x,0) for x in pnl),gross_closed_losers=-sum(min(x,0) for x in pnl),
        top_three_closed_winners=[dict(symbol=t['symbol'],pnl=t['pnl']) for t in winners[:3]],
        top_two_fraction_of_net_closed_pnl=(sum(t['pnl'] for t in winners[:2])/sum(pnl)) if sum(pnl)>0 else None,
        concentration_note='Attribution only; removing winners without rerunning account sizing is not a counterfactual return.',
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--old-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cohort={a['symbol']:a for a in json.loads((args.old_root/'cohort.json').read_text())}
    runs={}
    for name in ('primary','observed-5bp','observed-10bp','observed-25bp'):
        folder=args.root/name
        read=lambda n:json.loads((folder/(n+'.json')).read_text())
        validation=audit(folder)
        (folder/'independent-validation.json').write_text(json.dumps(validation,indent=2)+'\n')
        closed,fills,events,nav=map(read,('closed','fills','events','nav'))
        gaps=[e for e in events if e['kind']=='HELD_BAR_UNOBSERVED']
        summary=read('summary')
        runs[name]=dict(summary=summary,independent_accounting=validation,
            statistics=trade_statistics(closed,fills,cohort),monthly_nav=monthly_nav(nav),
            events=dict(Counter(e['kind'] for e in events)),
            gap_symbols=dict(Counter(e['symbol'] for e in gaps)),
            last_observed_nav_at=nav[-1]['at'] if nav else None,
            ending_exposure_fraction=nav[-1]['gross']/nav[-1]['equity'] if nav else None,
            mean_observed_exposure_fraction=mean(n['gross']/n['equity'] for n in nav) if nav else None,
            private_artifact_sha256={n:sha256((folder/(n+'.json')).read_bytes()).hexdigest()
                for n in ('summary','closed','fills','events','nav','positions','receivables','scans')})
    db=sqlite3.connect(args.root/'rth.sqlite')
    def rows(day):
        return json.loads(gzip.decompress(db.execute('SELECT data FROM bars WHERE symbol=? AND date=?',('SPY',day)).fetchone()[0]))
    first,last=rows('2025-04-28')[0],rows('2025-12-31')[-1]
    schedule={s['date']:s for s in json.loads((args.old_root/'schedule.json').read_text())}
    from strategy import stamp
    if stamp(first['start'])!=stamp(schedule['2025-04-28']['open']) or stamp(last['end'])!=stamp(schedule['2025-12-31']['close']):
        raise ValueError('BENCHMARK_BOUNDARY_BAR_MISSING')
    actions=normalized_actions(json.loads((args.root/'SPY-actions.json').read_text()),['SPY'])
    result=dict(runs=runs,benchmark=benchmark(first,last,actions),actual_orders=0,
        independent_out_of_sample=False,promotable=False,
        rule='Primary result remains HALT policy; observed-only outcomes cannot replace it.')
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
