from datetime import date,timedelta
import unittest

from spy_accumulation import dip_signal,simulate,xirr


def rows(count=340):
    return [dict(date=date(2019,1,1)+timedelta(days=i),open=100.,close=100.,adjclose=100.) for i in range(count)]


class AccumulationTests(unittest.TestCase):
    def simulate(self,data=None,arm='DIP5',cash_mode='ZERO',rates=(),cost_bps=0):
        data=rows() if data is None else data
        return simulate(data,start=data[253]['date'],end=data[-1]['date'],arm=arm,
            cash_mode=cash_mode,rates=rates,cost_bps=cost_bps)

    def test_exact_five_percent_boundary_and_prior_only_signal(self):
        d=rows();d[252]['close']=95.
        self.assertTrue(dip_signal(d,253))
        d[253]['close']=100000;d[253]['open']=1
        self.assertTrue(dip_signal(d,253))
        d[252]['close']=95.000001
        self.assertFalse(dip_signal(d,253))

    def test_current_high_reference_excludes_yesterday_and_drops_old_history(self):
        d=rows();d[0]['close']=999;d[252]['close']=100
        self.assertTrue(dip_signal(d,253))  # previous 252 reference still contains day0
        self.assertFalse(dip_signal(d,254)) # day0 has rolled out

    def test_no_dip_stays_cash_and_comparators_have_identical_contributions(self):
        out=[self.simulate(arm=a) for a in ('IMMEDIATE','DCA12','DIP5')]
        self.assertEqual(len({r['total_contributed'] for r in out}),1)
        self.assertEqual(out[-1]['purchase_days'],0)
        for r in out:self.assertAlmostEqual(r['final_wealth'],r['total_contributed'])

    def test_buy_is_next_open_not_signal_close_and_never_sells(self):
        d=rows();d[252]['close']=95;d[253]['open']=90;d[253]['close']=90;d[253]['adjclose']=90
        r=self.simulate(d)
        self.assertAlmostEqual(r['ledger'][0]['synthetic_adjusted_units'],10000/90)
        self.assertTrue(all(a['synthetic_adjusted_units']<=b['synthetic_adjusted_units']
                            for a,b in zip(r['ledger'],r['ledger'][1:])))

    def test_adjusted_series_dividend_proxy_without_double_cash_credit(self):
        d=rows();d[253]['open']=100;d[253]['close']=99;d[253]['adjclose']=100
        r=self.simulate(d,arm='IMMEDIATE')
        self.assertAlmostEqual(r['ledger'][0]['total'],9900)  # open factor100/99; actual intraday ex-date decline
        self.assertEqual(r['modeled_cash_interest'],0)

    def test_rate_is_lagged_before_previous_session(self):
        d=rows();prev=d[252]['date'];start=d[253]['date']
        rates=[(prev-timedelta(days=1),.01),(prev,.0365),(start,.30)]
        # Deposit is at start. On the next day, use prev's rate, not start's.
        r=simulate(d,start=start,end=d[254]['date'],arm='DIP5',cash_mode='TREASURY_PROXY',rates=rates)
        self.assertAlmostEqual(r['modeled_cash_interest'],1.)

    def test_rolling_high_not_all_time_high(self):
        d=rows();d[0]['close']=1000
        self.assertFalse(dip_signal(d,254))  # high day0 has rolled out

    def test_missing_rate_or_bad_prices_or_short_warmup_rejected(self):
        with self.assertRaises(ValueError):self.simulate(cash_mode='TREASURY_PROXY')
        d=rows();d[260]['adjclose']=float('nan')
        with self.assertRaises(ValueError):self.simulate(d)
        with self.assertRaises(ValueError):dip_signal(rows(),252)

    def test_deposits_do_not_hide_drawdown_in_unitized_equity(self):
        d=rows();d[260].update(open=50,close=50,adjclose=50)
        r=self.simulate(d,arm='IMMEDIATE')
        self.assertGreater(r['unitized_close_max_drawdown'],.49)

    def test_cost_scenario_reduces_wealth_and_does_not_spend_more_cash(self):
        a=self.simulate(arm='IMMEDIATE');b=self.simulate(arm='IMMEDIATE',cost_bps=5)
        self.assertLess(b['final_wealth'],a['final_wealth']);self.assertGreater(b['modeled_purchase_friction'],0)
        self.assertTrue(all(x['cash']>=-1e-8 for x in b['ledger']))

    def test_xirr_known_one_year_return(self):
        self.assertAlmostEqual(xirr([(date(2020,1,1),-100),(date(2021,1,1),110)]),1.1**(365.25/366)-1)

    def test_adjustment_global_scaling_does_not_change_wealth_or_signals(self):
        d=rows();base=self.simulate(d,arm='IMMEDIATE')
        for r in d:r['adjclose']*=.37
        scaled=self.simulate(d,arm='IMMEDIATE')
        self.assertAlmostEqual(base['final_wealth'],scaled['final_wealth'])
        self.assertEqual(base['purchase_days'],scaled['purchase_days'])

    def test_dividend_proxy_holding_does_not_double_credit_dividend(self):
        d=rows()
        for r in d[254:]:r.update(open=99,close=99,adjclose=100)
        r=self.simulate(d,arm='IMMEDIATE')
        self.assertAlmostEqual(r['final_wealth'],r['total_contributed'])
        self.assertEqual(r['modeled_cash_interest'],0)


if __name__=='__main__':unittest.main()
