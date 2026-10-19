from dataclasses import replace
from datetime import datetime,timedelta,timezone
import unittest

from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel.session_calendar import TradingSession
from rvol_filter import opening_rvol,replay_session


class RvolFilterTests(unittest.TestCase):
    def test_exact_boundary_and_no_same_day_in_denominator(self):
        self.assertTrue(opening_rvol([100]*14,100)['eligible'])
        self.assertFalse(opening_rvol([100]*14,'99.999999999')['eligible'])
        self.assertTrue(opening_rvol([100]*14,200)['eligible'])
        self.assertEqual(opening_rvol([100]*14,200)['prior_volume_sum'],'1400')

    def test_only_last_fourteen_prior_sessions_and_no_future_input(self):
        self.assertEqual(opening_rvol([999999]+[100]*14,100),opening_rvol([100]*14,100))

    def test_missing_zero_nonfinite_history_does_not_default_to_eligible(self):
        for history,current in [([1]*13,1),([1]*13+[0],1),([1]*14,0),([1]*14,'NaN')]:
            with self.assertRaises(ValueError):opening_rvol(history,current)

    def rows(self):
        start=datetime(2026,7,1,13,30,tzinfo=timezone.utc)
        s=TradingSession('2026-07-01',start,start+timedelta(minutes=30))
        rows=[MarketContext('QQQ',start+timedelta(minutes=i),'1m',100,101,99,100.5,10000) for i in range(30)]
        return s,rows

    def test_false_filter_suppresses_entry_without_changing_capital(self):
        s,rows=self.rows();r=replay_session(s,rows,100000,entry_eligible=False)
        self.assertTrue(r['gated_long']);self.assertEqual(r['fills'],[])
        self.assertEqual(r['report']['cash'],100000)

    def test_true_filter_leaves_frozen_fixture_result_exact(self):
        from dx27.research.opening_direction import OpeningDirectionFixture,MINUTE
        s,rows=self.rows();m=OpeningDirectionFixture(s,'R1')
        for b in rows:m.on_closed_minute(b.timestamp,b,as_of=b.timestamp+MINUTE)
        r=replay_session(s,rows,100000,entry_eligible=True)
        self.assertEqual(r['report'],m.report());self.assertEqual(r['decisions'],m.decisions)

    def test_missing_regular_minute_blocks_even_filtered_day(self):
        s,rows=self.rows();rows[10]=None
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):replay_session(s,rows,100000,entry_eligible=False)
        with self.assertRaises(ValueError):replay_session(s,rows[:-1],100000,entry_eligible=True)

    def test_variant_reuses_its_own_carried_capital(self):
        s,rows=self.rows();r=replay_session(s,rows,90000,entry_eligible=True)
        self.assertEqual(r['daily']['starting_equity'],90000)
        self.assertLessEqual(r['fills'][0]['quantity']*r['fills'][0]['price'],90000*.25)


if __name__=='__main__':unittest.main()
