"""Generate auditable Paper review intents from a sealed cross-asset snapshot.

Usage: python research/martin-luk/run.py --input snapshot.json --output result.json
No network, credentials, live endpoint, submission, or assumed entry fill.
"""
import argparse
import json
from pathlib import Path
from strategy import scan, entry_signal, allocate, manage, ema, canonical, seal, stamp


def run(bundle):
    if bundle['mode'] not in ('SYNTHETIC','HISTORICAL_REPLAY','PAPER_REVIEW'):
        raise ValueError('EXPLICIT_MODE_REQUIRED')
    snapshot = bundle['snapshot']
    if (bundle['mode']=='SYNTHETIC') != (snapshot['universe_kind']=='SYNTHETIC'):
        raise ValueError('SYNTHETIC_SOURCE_MODE_CONFLICT')
    plan = scan(snapshot)
    names = {a['symbol'] for a in snapshot['assets']}
    if set(bundle['intraday']) - names:
        raise ValueError('INTRADAY_SYMBOL_OUTSIDE_UNIVERSE')
    signals = []
    for c in plan['watchlist']:
        bars = bundle['intraday'].get(c['symbol'],[])
        if bars:
            signal = entry_signal(plan,c['symbol'],bars,bundle['asof'])
            if signal: signals.append(signal)
    a = bundle['account']
    if a['pending_orders_unaccounted']:
        raise ValueError('PENDING_RESERVATIONS_REQUIRED')
    allocation = allocate(signals,a['equity'],a['cash'],a['positions'])
    management=[]
    assets={a['symbol']:a for a in snapshot['assets']}
    for item in bundle.get('management',[]):
        if stamp(item['bar']['available_at']) > stamp(bundle['asof']):
            raise ValueError('FUTURE_MANAGEMENT_BAR')
        # At the official close, close < updated EMA9 iff close < prior EMA9.
        # Compute from validated premarket history, never trust a supplied future EMA.
        reference=ema([b['close'] for b in assets[item['symbol']]['daily']],9)[-1]
        management.append(dict(symbol=item['symbol'],result=manage(item['position'],
            item['bar'],reference,snapshot['session_close'])))
    return dict(version='MLP1',mode=bundle['mode'],input_sha256=seal(bundle),plan=plan,
        allocation=allocation,management_replay=management,execution_enabled=False,actual_fills=[],
        profit_estimate=None,limitations=[
            'Quantified adaptation of the pullback branch, not an exact discretionary replica.',
            'Broker reconciliation and fresh executable quotes required before submission.',
            'No profitability evidence or automatic Paper deployment claimed.'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    if args.input.resolve()==args.output.resolve():
        p.error('output must differ from input')
    bundle=json.loads(args.input.read_text(encoding='utf-8'),
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    result=run(bundle)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(canonical(result)+'\n',encoding='utf-8')
    print(json.dumps(dict(watchlist=len(result['plan']['watchlist']),
        intents=len(result['allocation']['intents']),mode=result['mode'],
        execution_enabled=False)))


if __name__=='__main__': main()
