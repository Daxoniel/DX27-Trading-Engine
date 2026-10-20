from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import unittest
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from example import fixture, intraday, bar
from history_data import NoRedirect
from history_replay import Replay
from history_screen import split_adjust, necessary, normalize_rth, aggregate
from strategy import scan, stamp
from audit_history import audit
from run_history import replay_manifest


def market():
    p=scan(fixture());morning=intraday(p)
    for b in morning:b['available_at']=(stamp(b['end'])+timedelta(seconds=1)).isoformat()
    rows=deepcopy(morning);t=stamp(rows[-1]['end']);price=rows[-1]['close']
    while t<stamp(p['session_close']):
        b=bar(t,5,price,price*1.001,price*.999,price)
        b['available_at']=(stamp(b['end'])+timedelta(seconds=1)).isoformat()
        rows.append(b);t+=timedelta(minutes=5)
    bars={c['symbol']:deepcopy(rows) for c in p['watchlist']}
    trails={c['symbol']:c['trail'] for c in p['watchlist']}
    return p,bars,trails


def tomorrow(plan,bars):
    p=deepcopy(plan);bs=deepcopy(bars)
    for k in ('asof','session_open','session_close'):p[k]=(stamp(p[k])+timedelta(days=1)).isoformat()
    for rows in bs.values():
        for b in rows:
            for k in ('start','end','available_at'):b[k]=(stamp(b[k])+timedelta(days=1)).isoformat()
    return p,bs


class HistoryTests(unittest.TestCase):
    def test_shared_cash_and_strict_signal_availability(self):
        p,bs,trails=market();r=Replay();r.session(p,bs,trails)
        self.assertEqual(len(r.fills),4)
        for f in r.fills:
            self.assertGreater(stamp(f['at']),stamp(f['signal_at']))
            self.assertLess(stamp(f['at']),stamp(f['expires_at']))
            self.assertLessEqual(f['price'],f['limit_price'])
        self.assertGreaterEqual(r.cash,0)
        paid=sum(Decimal(str(f['price']))*f['quantity'] for f in r.fills)
        self.assertAlmostEqual(float(Decimal(100000)-paid),r.cash,places=7)

    def test_future_bars_cannot_change_prior_entries(self):
        p,bs,trails=market();r=Replay();r.session(p,bs,trails)
        bs2=deepcopy(bs)
        for rows in bs2.values():
            for b in rows[20:]:
                for k in ('open','high','low','close'):b[k]*=.8
        other=Replay();other.session(p,bs2,trails)
        self.assertEqual([f for f in r.fills if f['side']=='buy'],[f for f in other.fills if f['side']=='buy'])

    def test_no_intrabar_touch_entry_and_no_reentry(self):
        p,bs,trails=market()
        for rows in bs.values():
            rows[4]['open']*=1.01;rows[4]['high']=max(rows[4]['high'],rows[4]['open'])
        r=Replay();r.session(p,bs,trails)
        self.assertFalse(r.fills)
        self.assertEqual(sum(e['kind']=='NO_OPEN_FILL_WITHIN_LIMIT' for e in r.events),4)

    def test_missing_opening_history_rejects_signal(self):
        p,bs,trails=market()
        for s in bs:bs[s]=bs[s][1:]
        r=Replay();r.session(p,bs,trails)
        self.assertFalse(r.fills);self.assertIsNone(r.halt)

    def test_missing_held_bar_halts_certified_nav(self):
        p,bs,trails=market();del bs['AAA'][10]
        r=Replay();r.session(p,bs,trails)
        self.assertEqual(r.halt['code'],'HELD_POSITION_BAR_MISSING')
        self.assertIsNone(r.report()['terminal_equity'])
        self.assertIsNone(r.report()['net_return'])

    def test_later_missing_bar_does_not_remove_earlier_entry(self):
        p,bs,trails=market();del bs['AAA'][-1]
        r=Replay();r.session(p,bs,trails)
        self.assertTrue(any(f['symbol']=='AAA' and f['side']=='buy' for f in r.fills))
        self.assertIsNotNone(r.halt)

    def test_later_invalid_bar_is_not_an_ex_post_entry_filter(self):
        p,bs,trails=market();bs['AAA'][10]['volume']=0
        r=Replay();r.session(p,bs,trails)
        self.assertTrue(any(f['symbol']=='AAA' and f['side']=='buy' for f in r.fills))
        self.assertEqual(r.halt['code'],'HELD_POSITION_BAR_INVALID')

    def test_closed_trade_and_cash_ledger_agree(self):
        p,bs,trails=market()
        for rows in bs.values():
            for b in rows[10:]:
                for k in ('open','high','low','close'):b[k]*=.9
        r=Replay();r.session(p,bs,trails)
        self.assertEqual(len(r.closed),4)
        self.assertFalse(r.positions)
        self.assertAlmostEqual(r.cash-100000,sum(t['pnl'] for t in r.closed),places=7)
        cash=Decimal(100000)
        for f in r.fills:cash+=(-1 if f['side']=='buy' else 1)*Decimal(str(f['price']))*f['quantity']
        self.assertAlmostEqual(float(cash),r.cash,places=7)

    def test_trail_waits_for_next_session_open(self):
        p,bs,trails=market();r=Replay()
        r.session(p,bs,{s:1_000_000 for s in trails})
        self.assertTrue(all(x['exit_pending'] for x in r.positions.values()))
        p2,bs2=tomorrow(p,bs);p2['watchlist']=[]
        for rows in bs2.values():
            for b in rows:
                for k in ('open','high','low','close'):b[k]*=.8
        r.session(p2,bs2,trails)
        self.assertFalse(r.positions)
        self.assertEqual({f['reason'] for f in r.fills if f['side']=='sell'},{'TRAIL_NEXT_OPEN'})

    def test_split_preserves_position_value_and_risk(self):
        p,bs,trails=market();r=Replay();r.session(p,bs,trails)
        old=deepcopy(r.positions['AAA']);equity=r.equity()
        r.actions('2025-10-21',[dict(kind='split',id='s1',symbol='AAA',date='2025-10-21',ratio=2)])
        new=r.positions['AAA']
        self.assertEqual(new['quantity'],old['quantity']*2)
        self.assertEqual(new['entry'],old['entry']/2)
        self.assertAlmostEqual(r.equity(),equity)
        r.actions('2025-10-21',[dict(kind='split',id='s1',symbol='AAA',date='2025-10-21',ratio=2)])
        self.assertEqual(r.positions['AAA']['quantity'],new['quantity'])

    def test_fractional_or_unknown_action_is_not_zeroed(self):
        for kind in ('split','stock_merger'):
            p,bs,trails=market();r=Replay();r.session(p,bs,trails)
            q=r.positions['AAA']['quantity']
            action=dict(kind=kind,id='x',symbol='AAA',date='2025-10-21',ratio=1/(q+1))
            r.actions('2025-10-21',[action])
            self.assertIsNotNone(r.halt)
            self.assertIn('AAA',r.positions)
            self.assertIsNone(r.report()['terminal_equity'])

    def test_dividend_receivable_is_not_spendable_before_pay_date(self):
        p,bs,trails=market();r=Replay();r.session(p,bs,trails)
        cash=r.cash;equity=r.equity();q=r.positions['AAA']['quantity']
        a=dict(kind='cash_dividend',id='d1',symbol='AAA',date='2025-10-21',rate=.2,payable_date='2025-10-30')
        r.actions('2025-10-21',[a]);self.assertEqual(r.cash,cash)
        self.assertAlmostEqual(r.equity(),equity+q*.2)
        r.actions('2025-10-30',[])
        self.assertAlmostEqual(r.cash,cash+q*.2);self.assertEqual(r.receivables,[])

    def test_future_split_does_not_rescale_earlier_signal_history(self):
        raw=[dict(t='2025-01-01T00:00:00Z',o=100,h=102,l=98,c=100,v=100)]
        split=[dict(ex_date='2025-06-01',old_rate=1,new_rate=2)]
        self.assertEqual(split_adjust(raw,'2025-05-31',split),raw)
        self.assertEqual(split_adjust(raw,'2025-06-01',split)[0]['c'],50)
        self.assertEqual(split_adjust(raw,'2025-06-01',split)[0]['v'],200)

    def test_regular_session_aggregation_excludes_extended_hours(self):
        s=dict(date='2025-10-20',open='2025-10-20T13:30:00Z',close='2025-10-20T13:40:00Z')
        raw=[dict(t=t,o=10,h=11,l=9,c=10,v=100) for t in
            ('2025-10-20T13:25:00Z','2025-10-20T13:30:00Z','2025-10-20T13:35:00Z','2025-10-20T13:40:00Z')]
        days,cov=normalize_rth(raw,[s]);self.assertTrue(cov['2025-10-20']['complete'])
        self.assertEqual(aggregate(days['2025-10-20'])['v'],200)

    def test_frozen_rules_or_out_of_order_session_rejected(self):
        p,bs,trails=market();r=Replay();r.session(p,bs,trails)
        with self.assertRaises(ValueError):r.session(p,bs,trails)
        p['rules']['risk_per_trade']=.1
        with self.assertRaises(ValueError):Replay().session(p,bs,trails)

    def test_authenticated_redirect_is_rejected(self):
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,302,'',{},'https://example.com')

    def disk_manifest(self,root):
        p,bs,trails=market();raw=json.dumps(dict(date='2025-10-20',plan=p,bars=bs,
            trails=trails,actions=[],warmup_exclusions=[])).encode()
        (root/'session.gz').write_bytes(gzip.compress(raw))
        m=dict(strategy_sha256=hashlib.sha256(Path(__file__).with_name('strategy.py').read_bytes()).hexdigest(),
            rules=p['rules'],initial_cash=100000,provenance={'kind':'SYNTHETIC'},
            sessions=[dict(path='session.gz',sha256=hashlib.sha256(raw).hexdigest())])
        (root/'manifest.json').write_text(json.dumps(m))
        return root/'manifest.json'

    def test_on_disk_replay_and_independent_audit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.disk_manifest(root)
            summary=replay_manifest(m,root/'report')
            self.assertEqual(summary['fills'],4)
            self.assertEqual(audit(root/'report')['status'],'PASS')

    def test_tampered_session_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.disk_manifest(root)
            (root/'session.gz').write_bytes(gzip.compress(b'{}'))
            with self.assertRaises(ValueError):replay_manifest(m,root/'report')

    def test_independent_audit_detects_cash_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.disk_manifest(root);replay_manifest(m,root/'report')
            p=root/'report'/'summary.json';x=json.loads(p.read_text());x['cash']+=1;p.write_text(json.dumps(x))
            with self.assertRaises(ValueError):audit(root/'report')


if __name__=='__main__':unittest.main()
