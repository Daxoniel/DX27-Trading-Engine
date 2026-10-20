"""Write an explicitly synthetic four-stock/two-sector input for the CLI.

The invented prices and schedule are software fixtures, not market evidence.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import argparse
from pathlib import Path
from strategy import canonical, scan


def bar(start, minutes, o, h, l, c, volume=1_000_000):
    end=start+timedelta(minutes=minutes)
    return dict(start=start.isoformat(),end=end.isoformat(),available_at=end.isoformat(),
        open=o,high=h,low=l,close=c,volume=volume)


def fixture():
    opening=datetime(2025,10,20,13,30,tzinfo=timezone.utc)
    previous=opening-timedelta(days=3,hours=-6,minutes=-30)
    daily=[]
    for i in range(160):
        close=50*1.006**min(i,100)*1.0008**max(0,i-100)
        daily.append(bar(previous-timedelta(days=159-i,hours=6,minutes=30),390,
            close*.9998,close*1.06,close*.999,close))
    assets=[dict(symbol=n,sector=sector,kind='US_COMMON_STOCK',tradable=True,
        known_at='2020-01-01T00:00:00+00:00',daily=deepcopy(daily))
        for n,sector in [('AAA','TECH'),('BBB','TECH'),('CCC','HEALTH'),('DDD','HEALTH')]]
    return dict(asof='2025-10-20T12:00:00+00:00',session_open=opening.isoformat(),
        session_close=(opening+timedelta(hours=6,minutes=30)).isoformat(),
        previous_session_close=previous.isoformat(),universe_kind='SYNTHETIC',assets=assets,
        price_basis='ASOF_SPLIT_ADJUSTED',adjustment_asof='2025-10-20T12:00:00+00:00',
        history_schedule=[(b['start'],b['end']) for b in daily])


def intraday(plan):
    support=plan['watchlist'][0]['support']
    t=datetime.fromisoformat(plan['session_open'])
    return [bar(t,5,support*1.004,support*1.006,support*.998,support*1.001),
        bar(t+timedelta(minutes=5),5,support*1.001,support*1.004,support*.997,support*1.002),
        bar(t+timedelta(minutes=10),5,support*1.002,support*1.009,support*1.001,support*1.008)]


def bundle():
    snapshot=fixture();bars=intraday(scan(snapshot))
    return dict(mode='SYNTHETIC',snapshot=snapshot,asof=bars[-1]['available_at'],
        intraday={a['symbol']:deepcopy(bars) for a in snapshot['assets']},
        account=dict(equity=100_000,cash=100_000,positions=[],pending_orders_unaccounted=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(canonical(bundle())+'\n',encoding='utf-8')
