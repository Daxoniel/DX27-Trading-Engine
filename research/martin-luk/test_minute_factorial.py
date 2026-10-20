from copy import deepcopy
from datetime import timedelta
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode

from example import fixture, intraday, bar
from minute_factorial import Replay, signal_for
from prepare_minute_factorial import aggregate
from strategy import Rules, stamp
from strategy_v2 import scan
from test_history import tomorrow
from strategy import canonical
from run_minute_factorial import run
from audit_minute_factorial import audit


def market(stop=False,second=False,prefill_low=False):
    plan=scan(fixture());plan['watchlist']=plan['watchlist'][:1]
    c=plan['watchlist'][0];symbol=c['symbol'];opening=stamp(plan['session_open']);support=c['support']
    price=support*1.008
    rows=[bar(opening+timedelta(minutes=i),1,price,price*1.001,price*.999,price) for i in range(390)]
    pattern=intraday(plan)
    for first in ([0,6] if second else [0]):
        for i,b in enumerate(pattern):
            rows[first+i].update({k:b[k] for k in ('open','high','low','close','volume')})
    if stop:rows[4]['low']=support*.99
    if prefill_low:rows[3]['low']=support*.9
    for b in rows:b['available_at']=(stamp(b['end'])+timedelta(seconds=1)).isoformat()
    minute={symbol:rows};five={symbol:aggregate(rows,opening)}
    def quote(s,at):return dict(t=at,bp=price*.999,ap=price,**{'as':1},c=['R'])
    return plan,minute,five,quote


class MinuteFactorialTests(unittest.TestCase):
    def test_one_minute_signal_still_waits_for_availability(self):
        p,one,five,q=market();r=Replay(minutes=1,quote_source=q)
        r.session(p,five,{},minute_bars=one)
        buy=next(f for f in r.fills if f['side']=='buy')
        self.assertEqual(stamp(buy['at'])-stamp(p['session_open']),timedelta(minutes=4))
        self.assertGreater(stamp(buy['at']),stamp(buy['signal_at']))
        self.assertLess(stamp(buy['at']),stamp(buy['expires_at']))

    def test_prefill_5m_low_cannot_stop_midbucket_entry(self):
        p,one,five,q=market(prefill_low=True);r=Replay(minutes=1,quote_source=q)
        r.session(p,five,{},minute_bars=one)
        self.assertEqual(len(r.positions),1)
        self.assertFalse(r.closed)

    def test_entry_minute_stop_is_processed(self):
        p,one,five,q=market(stop=True);r=Replay(minutes=1,quote_source=q)
        r.session(p,five,{},minute_bars=one)
        self.assertEqual(len(r.closed),1)
        self.assertEqual(stamp(r.closed[0]['exit_at'])-stamp(p['session_open']),timedelta(minutes=5,seconds=1))

    def test_reentry_requires_fresh_bars_after_observed_flat(self):
        p,one,five,q=market(stop=True,second=True)
        single=Replay(minutes=1,quote_source=q);single.session(p,five,{},minute_bars=one)
        repeat=Replay(minutes=1,reentry=True,quote_source=q);repeat.session(p,five,{},minute_bars=one)
        self.assertEqual(len([f for f in single.fills if f['side']=='buy']),1)
        buys=[f for f in repeat.fills if f['side']=='buy']
        self.assertEqual(len(buys),2)
        self.assertEqual(stamp(buys[1]['at'])-stamp(p['session_open']),timedelta(minutes=10))
        self.assertEqual(buys[1]['attempt_index'],2)
        self.assertEqual(buys[1]['prior_terminal_kind'],'EXIT')

    def test_no_pyramiding_when_reentry_enabled(self):
        p,one,five,q=market(second=True);r=Replay(minutes=1,reentry=True,quote_source=q)
        r.session(p,five,{},minute_bars=one)
        self.assertEqual(sum(f['side']=='buy' for f in r.fills),1)

    def test_new_setup_after_unfilled_attempt_is_identified(self):
        p,one,five,q=market(second=True);calls=[]
        def source(s,at):
            calls.append(at)
            return None if len(calls)==1 else q(s,at)
        r=Replay(minutes=1,reentry=True,quote_source=source);r.session(p,five,{},minute_bars=one)
        buy=next(f for f in r.fills if f['side']=='buy')
        self.assertEqual(buy['attempt_index'],2)
        self.assertEqual(buy['prior_terminal_kind'],'UNFILLED')
        self.assertEqual(buy['prior_fills_today'],0)

    def test_missing_early_minute_allows_only_new_contiguous_setup(self):
        p,one,five,q=market(second=True);symbol=p['watchlist'][0]['symbol'];del one[symbol][1]
        five={symbol:aggregate(one[symbol],stamp(p['session_open']))}
        r=Replay(minutes=1,quote_source=q);r.session(p,five,{},minute_bars=one)
        buy=next(f for f in r.fills if f['side']=='buy')
        self.assertEqual(stamp(buy['at'])-stamp(p['session_open']),timedelta(minutes=10))

    def test_complete_fresh_window_cannot_reuse_exit_bar(self):
        p,one,five,q=market();c=p['watchlist'][0];window=one[c['symbol']][:3]
        now=stamp(window[-1]['available_at'])
        self.assertIsNotNone(signal_for(p,c,window,now,1,stamp(p['session_open']),Rules()))
        self.assertIsNone(signal_for(p,c,window,now,1,stamp(window[0]['end']),Rules()))
        with self.assertRaises(ValueError):signal_for(p,c,window,now-timedelta(seconds=2),1,stamp(p['session_open']),Rules())

    def test_five_minute_signal_uses_same_one_minute_execution_clock(self):
        p,one,five,q=market();symbol=p['watchlist'][0]['symbol'];patterns=intraday(p)
        rows=[];opening=stamp(p['session_open'])
        for i,b in enumerate(patterns):
            for j in range(5):
                row=bar(opening+timedelta(minutes=i*5+j),1,b['open'],b['high'],b['low'],b['close'])
                row['available_at']=(stamp(row['end'])+timedelta(seconds=1)).isoformat();rows.append(row)
        rows.extend(one[symbol][15:]);one={symbol:rows};five={symbol:aggregate(rows,opening)}
        r=Replay(minutes=5,quote_source=q);r.session(p,five,{},minute_bars=one)
        buy=next(f for f in r.fills if f['side']=='buy')
        self.assertEqual(stamp(buy['at'])-opening,timedelta(minutes=16))

    def test_daily_exit_cash_recognized_after_opening_bar_is_observed(self):
        p,one,five,q=market();r=Replay(minutes=1,quote_source=q);r.session(p,five,{},minute_bars=one)
        p2,five2=tomorrow(p,five);_,one2=tomorrow(p,one);p2['watchlist']=[]
        symbol=next(iter(r.positions))
        r.session(p2,five2,{symbol:True},minute_bars=one2)
        sell=next(f for f in r.fills if f['side']=='sell')
        self.assertEqual(stamp(sell['at'])-stamp(p2['session_open']),timedelta(minutes=5,seconds=1))
        self.assertIsNone(r.halt)

    def test_disk_run_and_independent_fresh_window_audit_reject_tampering(self):
        p,one,five,source=market(stop=True,second=True)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);quote_root=root/'quotes';quote_root.mkdir()
            class Quotes:
                cache=SimpleNamespace(root=quote_root)
                used={}
                def __call__(self,symbol,at):
                    q=source(symbol,at)
                    params=dict(symbols=symbol,start=(stamp(at)-timedelta(seconds=60)).isoformat(),
                        end=at,feed='sip',asof='2025-04-25',sort='desc',limit=1)
                    url='https://data.alpaca.markets/v2/stocks/quotes?'+urlencode(sorted(params.items()))
                    key=sha256(url.encode()).hexdigest();raw=canonical(dict(quotes={symbol:[q]})).encode()
                    digest=sha256(raw).hexdigest();meta=dict(url=url,sha256=digest,bytes=len(raw))
                    (quote_root/(key+'.json.gz')).write_bytes(gzip.compress(raw))
                    (quote_root/(key+'.meta.json')).write_text(canonical(meta))
                    self.used[key]=dict(sha256=digest,bytes=len(raw));return q
            payload=dict(date=p['session_open'][:10],plan=p,bars=five,minute_bars=one,daily_exit={},actions=[])
            filename=payload['date']+'.json.gz'
            raw=canonical(payload).encode();(root/filename).write_bytes(gzip.compress(raw))
            manifest=dict(initial_cash=100000,provenance=dict(synthetic=True),
                sessions=[dict(path=filename,sha256=sha256(raw).hexdigest())])
            path=root/'manifest.json';path.write_text(canonical(manifest));output=root/'run'
            run(path,output,Quotes(),1,True,5,'OBSERVED_ONLY')
            result=audit(output,path,quote_root)
            self.assertEqual(result['signal_windows_checked'],2)
            fills=json.loads((output/'fills.json').read_text());fills[0]['signal_evidence_sha256']='0'*64
            (output/'fills.json').write_text(canonical(fills))
            with self.assertRaisesRegex(ValueError,'SIGNAL_EVIDENCE_SEAL_FAILED'):audit(output,path,quote_root)


if __name__=='__main__':unittest.main()
