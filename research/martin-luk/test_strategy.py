from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from strategy import Rules, scan, entry_signal, allocate, manage
from run import run


from example import bar, fixture, intraday


class StrategyTests(unittest.TestCase):
    def test_cross_sector_universe_not_soxl(self):
        p=scan(fixture())
        self.assertEqual({x['symbol'] for x in p['watchlist']},{'AAA','BBB','CCC','DDD'})
        self.assertEqual({x['sector'] for x in p['watchlist']},{'TECH','HEALTH'})
        self.assertFalse(p['execution_enabled'])

    def test_remove_sector_peer_and_recompute(self):
        s=fixture();s['assets'].pop()
        self.assertEqual({x['symbol'] for x in scan(s)['watchlist']},{'AAA','BBB'})

    def test_reject_noncommon_and_low_liquidity(self):
        s=fixture();s['assets'][0]['kind']='LEVERAGED_ETF'
        for b in s['assets'][1]['daily']:b['volume']=10
        p=scan(s)
        self.assertEqual({x['symbol'] for x in p['watchlist']},{'CCC','DDD'})

    def test_future_daily_or_classification_fails(self):
        for target in ('available_at','known_at'):
            s=fixture()
            if target=='known_at':s['assets'][0][target]='2026-01-01T00:00:00Z'
            else:s['assets'][0]['daily'][-1][target]='2026-01-01T00:00:00Z'
            with self.assertRaises(ValueError):scan(s)

    def test_stale_or_unsorted_daily_fails(self):
        for case in ('stale','order'):
            s=fixture()
            if case=='stale':s['assets'][0]['daily'].pop()
            else:s['assets'][0]['daily'].reverse()
            with self.assertRaises(ValueError):scan(s)

    def test_flush_reclaim_and_signal_identity(self):
        p=scan(fixture());bs=intraday(p);now=bs[-1]['available_at']
        s=entry_signal(p,'AAA',bs,now)
        self.assertIsNotNone(s)
        self.assertEqual(s,entry_signal(p,'AAA',bs,now))
        self.assertLess(s['stop_price'],s['limit_price'])
        bs[-1]['close']=bs[-1]['open']
        self.assertIsNone(entry_signal(p,'AAA',bs,now))

    def test_signal_availability_does_not_require_same_provider_receipt_instant(self):
        p=scan(fixture());bs=intraday(p)
        at=datetime.fromisoformat(bs[-1]['available_at'])
        signal=entry_signal(p,'AAA',bs,(at+timedelta(seconds=10)).isoformat())
        self.assertEqual(signal['signal_at'],bs[-1]['available_at'])
        self.assertIsNone(entry_signal(p,'AAA',bs,(at+timedelta(seconds=61)).isoformat()))

    def test_missing_bar_and_future_bar_fail(self):
        p=scan(fixture());bs=intraday(p)
        with self.assertRaises(ValueError):entry_signal(p,'AAA',bs,bs[-2]['available_at'])
        bs.insert(1,deepcopy(bs[0]))
        with self.assertRaises(ValueError):entry_signal(p,'AAA',bs,bs[-1]['available_at'])

    def test_cash_sector_risk_and_duplicate_reservations(self):
        p=scan(fixture());bs=intraday(p)
        ss=[entry_signal(p,n,bs,bs[-1]['available_at']) for n in ('AAA','BBB','CCC','DDD')]
        result=allocate(ss+[ss[0]],100_000,60_000,[])
        self.assertLessEqual(result['reserved_gross'],60_000)
        self.assertLessEqual(result['reserved_risk'],2_000)
        self.assertTrue(result['remaining_cash']>=0)
        for sector in ('TECH','HEALTH'):
            self.assertLessEqual(sum(s['quantity']*s['limit_price'] for s in result['intents'] if s['sector']==sector),50_000)
        for s in result['intents']:self.assertLessEqual(s['planned_risk'],500)
        self.assertEqual(result['rejected'][-1]['reason'],'DUPLICATE_OR_HELD')

    def test_existing_and_pending_positions_reserve_capacity(self):
        p=scan(fixture());bs=intraday(p);s=entry_signal(p,'AAA',bs,bs[-1]['available_at'])
        positions=[dict(symbol='AAA',sector='TECH',quantity=100,mark=100,stop_price=99)]
        self.assertFalse(allocate([s],100_000,90_000,positions)['intents'])

    def test_pending_other_symbol_reserves_cash(self):
        p=scan(fixture());bs=intraday(p);s=entry_signal(p,'AAA',bs,bs[-1]['available_at'])
        positions=[dict(symbol='OTHER',sector='OTHER',quantity=100,mark=100,stop_price=99,pending=True)]
        self.assertFalse(allocate([s],100_000,10_000,positions)['intents'])

    def test_prior_pullback_is_rejected(self):
        s=fixture()
        s['assets'][0]['daily'][-8]['low'] *= .98
        p=scan(s)
        self.assertEqual(next(x['reason'] for x in p['rejected'] if x['symbol']=='AAA'),'PRIOR_PULLBACK_EPISODE')

    def test_missing_middle_session_and_bad_basis_fail(self):
        s=fixture();del s['assets'][0]['daily'][-10]
        with self.assertRaises(ValueError):scan(s)
        s=fixture();s['price_basis']='RETROSPECTIVE_TOTAL_RETURN'
        with self.assertRaises(ValueError):scan(s)

    def test_invalid_risk_configuration(self):
        for kwargs in [dict(risk_per_trade=float('nan')),dict(max_gross=3),dict(min_stop=.05)]:
            with self.assertRaises(ValueError):Rules(**kwargs)

    def position(self):
        return dict(entry=100,initial_stop=98,stop_price=98,quantity=100,
            initial_quantity=100,partial_taken=False,exit_pending=False,
            filled_at='2025-10-20T13:30:00Z')

    def test_management_rejects_duplicate_and_pre_fill_bars(self):
        t=datetime(2025,10,20,13,30,tzinfo=timezone.utc)
        b=bar(t,5,100,101,99,100)
        r=manage(self.position(),b,99,'2025-10-20T20:00:00Z')
        with self.assertRaises(ValueError):manage(r['position'],b,99,'2025-10-20T20:00:00Z')
        b=bar(t-timedelta(minutes=5),5,100,101,99,100)
        with self.assertRaises(ValueError):manage(self.position(),b,99,'2025-10-20T20:00:00Z')

    def test_ipo_short_history_is_excluded_without_halting_others(self):
        s=fixture();s['assets'][0]['daily']=s['assets'][0]['daily'][-30:]
        p=scan(s)
        self.assertEqual(next(x['reason'] for x in p['rejected'] if x['symbol']=='AAA'),'INSUFFICIENT_HISTORY')
        self.assertEqual({c['symbol'] for c in p['watchlist']},{'CCC','DDD'})

    def test_gap_stop_and_stop_first_ambiguity(self):
        t=datetime(2025,10,20,13,30,tzinfo=timezone.utc)
        for o,h,l,price in [(95,107,94,95),(100,107,97,98)]:
            b=bar(t,5,o,h,l,100 if o==100 else 96)
            r=manage(self.position(),b,99,'2025-10-20T20:00:00Z')
            self.assertIsNone(r['position'])
            self.assertEqual(r['fills'][0]['price'],price*.9995)
            self.assertEqual(r['fills'][0]['reason'],'STOP')

    def test_partial_once_and_close_trail_next_open(self):
        t=datetime(2025,10,20,13,30,tzinfo=timezone.utc)
        b=bar(t,5,101,107,100,106)
        r=manage(self.position(),b,107,'2025-10-20T20:00:00Z')
        self.assertEqual(r['fills'][0]['quantity'],15)
        self.assertFalse(r['position']['exit_pending'])
        b=bar(t+timedelta(hours=6,minutes=25),5,104,107,102,103)
        r=manage(r['position'],b,104,'2025-10-20T20:00:00Z')
        self.assertEqual(r['fills'],[])
        self.assertTrue(r['position']['exit_pending'])
        b=bar(t+timedelta(days=1),5,90,93,89,92)
        r=manage(r['position'],b,104,'2025-10-21T20:00:00Z')
        self.assertEqual(r['fills'][0]['quantity'],85)
        self.assertEqual(r['fills'][0]['price'],90*.9995)

    def test_end_to_end_bundle_no_fabricated_fills(self):
        s=fixture();p=scan(s);bs=intraday(p)
        bundle=dict(mode='SYNTHETIC',snapshot=s,asof=bs[-1]['available_at'],
            intraday={a['symbol']:deepcopy(bs) for a in s['assets']},
            account=dict(equity=100_000,cash=100_000,positions=[],pending_orders_unaccounted=False))
        result=run(bundle)
        self.assertEqual(len(result['allocation']['intents']),4)
        self.assertEqual(result['actual_fills'],[])
        self.assertIsNone(result['profit_estimate'])
        self.assertEqual(result,run(bundle))


if __name__=='__main__':unittest.main()
