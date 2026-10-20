from copy import deepcopy
from datetime import timedelta
import unittest

from capture_replay_v2 import merge_rows
from example import fixture, intraday, bar
from history_replay_v2 import Replay
from prepare_replay_v2 import daily_exit_flags, normalized_actions
from strategy import stamp
from strategy_v2 import scan
from test_history import tomorrow


def market():
    p = scan(fixture()); rows = intraday(p)
    t = stamp(rows[-1]['end']);price = rows[-1]['close']
    while t < stamp(p['session_close']):
        rows.append(bar(t,5,price,price*1.001,price*.999,price));t+=timedelta(minutes=5)
    for b in rows: b['available_at']=(stamp(b['end'])+timedelta(seconds=1)).isoformat()
    return p,{c['symbol']:deepcopy(rows) for c in p['watchlist']}


class ReplayV2Tests(unittest.TestCase):
    def test_full_account_and_no_same_bar_entry(self):
        p,bs = market();r=Replay();r.session(p,bs,{})
        self.assertEqual(len(r.positions),4)
        self.assertTrue(all(f['price']<=f['limit_price'] and stamp(f['at'])>stamp(f['signal_at']) for f in r.fills))
        self.assertAlmostEqual(r.cash+sum(x['quantity']*x['mark'] for x in r.positions.values()),r.equity())
        self.assertGreaterEqual(r.cash,0)

    def test_daily_exit_is_known_next_session_and_uses_open(self):
        p,bs=market();r=Replay();r.session(p,bs,{s:True for s in bs})
        self.assertEqual(len(r.positions),4)  # today's future daily exit cannot close a new entry
        p2,bs2=tomorrow(p,bs);p2['watchlist']=[]
        r.session(p2,bs2,{s:True for s in bs})
        self.assertFalse(r.positions)
        self.assertEqual({f['reason'] for f in r.fills if f['side']=='sell'},{'TRAIL_NEXT_OPEN'})
        self.assertTrue(all(f['at']==p2['session_open'] for f in r.fills if f['side']=='sell'))

    def test_intraday_close_does_not_substitute_vendor_daily_close(self):
        p,bs=market();r=Replay();r.session(p,bs,{})
        self.assertFalse(any(x['exit_pending'] for x in r.positions.values()))
        p2,bs2=tomorrow(p,bs);p2['watchlist']=[]
        for rows in bs2.values():
            for b in rows:
                for k in ('open','high','low','close'): b[k]=rows[-1]['close']
        r.session(p2,bs2,{s:False for s in bs})
        self.assertEqual(len(r.positions),4)

    def test_primary_halts_secondary_records_gap_and_uses_later_gap_open(self):
        p,bs=market();del bs['AAA'][10]
        for b in bs['AAA'][10:]:
            for k in ('open','high','low','close'): b[k]*=.9
        primary=Replay();primary.session(p,bs,{})
        self.assertEqual(primary.halt['code'],'HELD_POSITION_BAR_MISSING')
        self.assertIsNone(primary.report()['net_return'])
        secondary=Replay(gap_policy='OBSERVED_ONLY');secondary.session(p,bs,{})
        self.assertIsNone(secondary.halt)
        self.assertEqual(secondary.report()['held_unobserved_bars'],1)
        sell=next(f for f in secondary.fills if f['symbol']=='AAA' and f['side']=='sell')
        self.assertAlmostEqual(sell['price'],bs['AAA'][10]['open']*.9995)
        self.assertFalse(secondary.report()['nav_certified'])

    def test_invalid_held_bars_halt_even_secondary(self):
        p,bs=market();bs['AAA'][10]['close']=float('nan')
        r=Replay(gap_policy='OBSERVED_ONLY');r.session(p,bs,{})
        self.assertEqual(r.halt['code'],'HELD_POSITION_BAR_INVALID')

    def test_missing_daily_history_cannot_keep_held_position_silently(self):
        p,bs=market();r=Replay();r.session(p,bs,{})
        p2,bs2=tomorrow(p,bs);r.session(p2,bs2,{})
        self.assertEqual(r.halt['code'],'HELD_POSITION_DAILY_HISTORY_MISSING')

    def test_no_future_daily_value_used_by_exit_flags(self):
        prior=[dict(date=str(i)) for i in range(160)]
        rows={str(i):dict(t=str(i),o=100,h=110,l=80,c=100 if i<159 else 90,v=1000) for i in range(160)}
        expected=daily_exit_flags('2025-01-01',prior,{'AAA':rows},{})
        rows['future']=dict(t='future',o=1,h=1,l=1,c=1,v=1000)
        self.assertEqual(expected,{'AAA':True})
        self.assertEqual(daily_exit_flags('2025-01-01',prior,{'AAA':rows},{}),expected)

    def test_source_revision_never_silently_replaces_bar(self):
        b=dict(t='2025-01-01',o=1)
        self.assertEqual(merge_rows([b],[b]),[b])
        with self.assertRaisesRegex(ValueError,'OVERLAPPING_SOURCE_REVISION'):
            merge_rows([b],[dict(b,o=2)])

    def test_action_aliases_preserve_effective_date(self):
        data=dict(name_changes=[dict(old_symbol='OLD',new_symbol='NEW')],
            cash_dividends=[dict(id='d',symbol='NEW',ex_date='2025-06-01',payable_date='2025-06-30',rate=.2)])
        acts=normalized_actions(data,['OLD'])
        self.assertEqual(acts[0]['symbol'],'OLD')
        self.assertEqual(acts[0]['date'],'2025-06-01')
        self.assertEqual(acts[0]['kind'],'cash_dividend')


if __name__=='__main__':unittest.main()
