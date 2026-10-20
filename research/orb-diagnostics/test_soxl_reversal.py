import math
import unittest

from check_soxl_reversal import assemble, validate_bar
from soxl_reversal import (block_intervals, break_even_bps, direction, regression,
                           simulate, summarize, trade_return)


def bar(price=100):
    return dict(o=price, h=price, l=price, c=price, v=1000)


def opening(price=99, exit_price=100):
    minutes = {f'09:{i:02}': bar(price) for i in range(30, 60)}
    minutes['10:00'] = bar(exit_price)
    return minutes


def session(day='2024-01-03', gap=-.01):
    return dict(date=day, gap=gap, minutes=opening(), ex_dividend=False)


class SoxlReversalTests(unittest.TestCase):
    def test_sign_rule_and_zero_gap_are_explicit(self):
        self.assertEqual(direction(-.01, 'GAP_DOWN_LONG'), 1)
        self.assertEqual(direction(0, 'GAP_DOWN_LONG'), 0)
        self.assertEqual(direction(0, 'TWO_SIDED'), -1)
        self.assertEqual(direction(-.01, 'GAP_UP_SHORT'), 0)
        with self.assertRaises(ValueError):
            direction(float('nan'), 'GAP_DOWN_LONG')

    def test_costs_apply_adversely_on_both_sides(self):
        self.assertAlmostEqual(trade_return(100, 102, 1, 5), 102*.9995/(100*1.0005)-1)
        self.assertAlmostEqual(trade_return(100, 98, -1, 5), (100*.9995-98*1.0005)/100)
        self.assertLess(trade_return(100, 100, 1, 5), 0)
        self.assertLess(trade_return(100, 100, -1, 5), 0)

    def test_delayed_entry_cannot_use_the_signal_open_price(self):
        r = session()
        r['minutes']['09:32'] = bar(101)
        ideal = simulate([r], arm='GAP_DOWN_LONG', entry='09:30', bps=0)
        delayed = simulate([r], arm='GAP_DOWN_LONG', bps=0)
        self.assertGreater(ideal['ledger'][0]['trade_return'], 0)
        self.assertLess(delayed['ledger'][0]['trade_return'], 0)

    def test_exit_is_1000_open_not_close_or_later_extreme(self):
        r = session()
        a = simulate([r], arm='GAP_DOWN_LONG')
        r['minutes']['10:00'].update(c=1000, h=1000, l=.01)
        b = simulate([r], arm='GAP_DOWN_LONG')
        self.assertEqual(a, b)

    def test_future_session_does_not_change_prior_positions_or_returns(self):
        rows = [session(), session('2024-01-04', .01)]
        a = simulate(rows, arm='TWO_SIDED')['ledger'][0]
        rows[1]['minutes'] = opening(10000, 1)
        self.assertEqual(a, simulate(rows, arm='TWO_SIDED')['ledger'][0])

    def test_nontrade_is_zero_return_and_not_counted_as_a_win(self):
        rows = [session(gap=.01), session('2024-01-04')]
        r = simulate(rows, arm='GAP_DOWN_LONG')
        self.assertEqual(r['summary']['sessions'], 2)
        self.assertEqual(r['summary']['trades'], 1)
        self.assertEqual(r['ledger'][0]['portfolio_return'], 0)

    def test_compounding_and_allocation_are_account_based(self):
        r = simulate([session(), session('2024-01-04')], arm='GAP_DOWN_LONG', bps=0)
        expected = (1+.25*(100/99-1))**2
        self.assertAlmostEqual(r['summary']['final_equity'], 100000*expected)
        with self.assertRaises(ValueError):
            simulate([session()], arm='GAP_DOWN_LONG', allocation=3)

    def test_exact_previous_session_missing_does_not_bridge(self):
        calendar = [('2024-01-02', '15:59'), ('2024-01-03', '15:59'), ('2024-01-04', '15:59')]
        minutes = {'2024-01-02': {'15:59': bar()}, '2024-01-04': opening()}
        rows, excluded = assemble(calendar, minutes, set())
        self.assertFalse(rows)
        self.assertIn('MISSING_EXACT_PREVIOUS_SESSION_FINAL_MINUTE', excluded[-1]['reasons'])

    def test_half_day_close_and_full_minute_coverage(self):
        calendar = [('2024-11-29', '12:59'), ('2024-12-02', '15:59')]
        minutes = {'2024-11-29': {'12:59': bar()}, '2024-12-02': opening()}
        rows, excluded = assemble(calendar, minutes, {'2024-12-02'})
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['ex_dividend'])
        self.assertAlmostEqual(rows[0]['gap'], -.01)
        del minutes['2024-12-02']['09:49']
        rows, excluded = assemble(calendar, minutes, set())
        self.assertFalse(rows)
        self.assertIn('MISSING_OPENING_MINUTES:09:49', excluded[-1]['reasons'])

    def test_invalid_ohlc_and_nonfinite_values_rejected(self):
        for changes in [dict(o=math.inf), dict(l=101), dict(h=99), dict(c=-1), dict(v=-1), dict(o=True)]:
            b = bar()
            b.update(changes)
            self.assertFalse(validate_bar(b))

    def test_drawdown_and_loss_streak_use_actual_compounded_trades(self):
        rows = [session(), session('2024-01-04'), session('2024-01-05')]
        for r in rows:
            r['minutes'] = opening(100, 90)
        s = simulate(rows, arm='GAP_DOWN_LONG', bps=0)['summary']
        self.assertAlmostEqual(s['end_of_trade_max_drawdown'], 1-.975**3)
        self.assertEqual(s['longest_losing_trade_streak'], 3)
        self.assertEqual(s['net_trade_win_rate'], 0)

    def test_block_bootstrap_is_paired_reproducible_and_keeps_nontrades(self):
        rows = [session(f'2024-01-{i:02}', -.01 if i%2 else .01) for i in range(1, 21)]
        a = simulate(rows, arm='GAP_DOWN_LONG')['ledger']
        b = simulate(rows, arm='ALWAYS_LONG')['ledger']
        one = block_intervals(a, b, replicates=50, block=3)
        self.assertEqual(one, block_intervals(a, b, replicates=50, block=3))
        self.assertEqual(block_intervals(b, b, replicates=50, block=3)
                         ['mean_portfolio_daily_excess_vs_always_long_bps95'], [0, 0])
        b[0]['date'] = 'wrong'
        with self.assertRaises(ValueError):
            block_intervals(a, b, replicates=2)

    def test_regression_recovers_known_negative_relationship(self):
        rows = []
        for i in range(30):
            gap = (i-15)/1000
            r = session(gap=gap)
            r['minutes'] = opening(100, 100*(1+.001-.3*gap))
            rows.append(r)
        result = regression(rows)
        self.assertAlmostEqual(result['beta'], -.3)
        self.assertAlmostEqual(result['intercept'], .001)
        self.assertAlmostEqual(result['r_squared'], 1)

    def test_break_even_cost_and_monotonic_friction(self):
        rows = [session()]
        bps = break_even_bps(rows)
        self.assertAlmostEqual(trade_return(99, 100, 1, bps), 0)
        self.assertGreater(trade_return(99, 100, 1, 2), trade_return(99, 100, 1, 5))
        rows[0]['minutes'] = opening(100, 90)
        self.assertEqual(break_even_bps(rows), 0)


if __name__ == '__main__':
    unittest.main()
