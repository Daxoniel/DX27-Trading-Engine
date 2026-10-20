"""Independent Decimal ledger audit. Does not import the strategy or replay.

This checks accounting and modeled timing, not source authenticity or edge.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import argparse
import json
from pathlib import Path


def audit(root):
    root=Path(root)
    read=lambda name:json.loads((root/(name+'.json')).read_text(encoding='utf-8'))
    summary,fills,closed,events,positions,receivables,nav=(read(n) for n in
        ('summary','fills','closed','events','positions','receivables','nav'))
    checks=[]
    def check(ok,label):
        if not ok:raise ValueError(label)
        checks.append(label)
    dec=lambda x:Decimal(str(x))
    near=lambda a,b:abs(dec(a)-dec(b))<Decimal('.000001')
    cash=dec(summary['initial_cash']);bought=defaultdict(Decimal);sold=defaultdict(Decimal)
    for f in fills:
        amount=dec(f['price'])*f['quantity'];tid=f['trade_id']
        check(f['quantity']>0 and f['price']>0,'positive_execution_values')
        if f['side']=='buy':
            cash-=amount;bought[tid]+=amount
            parse=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
            check(parse(f['signal_at'])<parse(f['at'])<parse(f['expires_at']),'entry_after_signal_before_expiry')
            check(f['price']<=f['limit_price'],'buy_limit_respected')
        elif f['side']=='sell':cash+=amount;sold[tid]+=amount
        else:raise ValueError('INVALID_FILL_SIDE')
    accrued=defaultdict(Decimal)
    for e in events:
        if e['kind']=='DIVIDEND_PAID':cash+=dec(e['amount'])
        if e['kind']=='DIVIDEND_ACCRUED':accrued[e['trade_id']]+=dec(e['amount'])
    check(near(cash,summary['cash']),'cash_rebuilt_from_executions_and_paid_dividends')
    equity=cash+sum(dec(p['mark'])*p['quantity'] for p in positions.values())+sum(dec(r['amount']) for r in receivables)
    check(near(equity,summary['last_known_equity']),'equity_includes_inventory_and_receivables')
    check(summary['open_positions']==len(positions),'open_position_count')
    check(summary['closed_trades']==len(closed),'closed_trade_count')
    check(near(equity-dec(summary['initial_cash']),dec(summary['closed_trade_pnl'])+
        dec(summary['open_trade_marked_pnl_including_partials'])),'closed_and_open_trade_pnl_reconciles_with_equity')
    for t in closed:
        tid=t['trade_id'];pnl=sold[tid]+accrued[tid]-bought[tid]
        check(near(pnl,t['pnl']),'closed_trade_cash_flow_pnl')
    timeline=[]
    for f in fills:timeline.append((f['at'],'FILL',f))
    for e in events:
        if e['kind']=='SPLIT':timeline.append((e['date']+'T00:00:00+00:00','SPLIT',e))
    inventory=defaultdict(Decimal)
    for _,kind,x in sorted(timeline,key=lambda x:x[0]):
        tid=x['trade_id']
        if kind=='SPLIT':inventory[tid]*=dec(x['ratio'])
        else:inventory[tid]+=dec(x['quantity'])*(1 if x['side']=='buy' else -1)
        check(inventory[tid]>=0,'no_short_inventory_created')
    remaining={p['trade_id']:p['quantity'] for p in positions.values()}
    for tid,q in inventory.items():check(near(q,remaining.get(tid,0)),'inventory_reconciles_after_splits')
    peak=dec(summary['initial_cash']);dd=Decimal(0)
    for n in nav:
        value=dec(n['equity']);peak=max(peak,value);dd=max(dd,1-value/peak)
    check(near(dd,summary['max_observed_bar_close_drawdown']),'bar_close_drawdown_rebuilt')
    if summary['halt']:
        check(summary['terminal_equity'] is None and summary['net_return'] is None,'incomplete_accounting_not_reported_as_final_return')
    else:
        check(near(equity/dec(summary['initial_cash'])-1,summary['net_return']),'terminal_return_rebuilt')
    return dict(status='PASS',checks=len(checks),source_authenticity_verified=False,
        execution_model_verified_against_quotes=False,promotable=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();result=audit(a.report)
    (a.report/'independent-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
