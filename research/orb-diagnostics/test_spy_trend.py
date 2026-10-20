from calendar import monthrange
from datetime import date,timedelta
import unittest

from spy_accumulation import simulate
from spy_trend import monthly_targets,recovery_stats,simulate_trend


def data():
    start=date(1998,1,1);end=date(2002,12,31);rows=[];ends=set()
    for i in range((end-start).days+1):
        day=start+timedelta(days=i)
        price=100. if day<date(1999,12,1) else 110.
        rows.append(dict(date=day,open=price,close=price,adjclose=price))
        if day.day==monthrange(day.year,day.month)[1]:ends.add(day)
    return rows,ends


class TrendTests(unittest.TestCase):
    def run_model(self,rows=None,ends=None,**kw):
        if rows is None:rows,ends=data()
        defaults=dict(start=date(2000,1,1),end=date(2001,12,31),arm='SMA10',cash_mode='ZERO',rates=[],month_end_dates=ends)
        defaults.update(kw);return simulate_trend(rows,**defaults)

    def test_ten_completed_months_current_month_in_sma_and_total_return_signal(self):
        rows,ends=data();r=monthly_targets(rows,ends)
        self.assertNotIn(date(1998,9,30),r)
        self.assertAlmostEqual(r[date(1999,12,31)]['sma10'],101)
        self.assertTrue(r[date(1999,12,31)]['long'])
        for row in rows:row['close']=100 # adjusted series remains the signal
        self.assertEqual(r,monthly_targets(rows,ends))

    def test_equality_preserves_last_direction(self):
        rows,ends=data();r=monthly_targets(rows,ends)
        self.assertFalse(r[date(1998,10,31)]['long'])
        self.assertEqual(r[date(2000,10,31)]['month_close'],r[date(2000,10,31)]['sma10'])
        self.assertTrue(r[date(2000,10,31)]['long'])

    def test_no_intramonth_exit_and_month_close_signal_executes_next_open(self):
        rows,ends=data()
        for row in rows:
            if row['date']>=date(2000,1,10):row.update(open=80,close=80,adjclose=80)
        r=self.run_model(rows,ends)
        sale=[f for f in r['fills'] if f['side']=='sell'][0]
        self.assertEqual(sale['signal_date'],'2000-01-31');self.assertEqual(sale['date'],'2000-02-01')
        jan31=next(x for x in r['ledger'] if x['date']=='2000-01-31')
        self.assertGreater(jan31['synthetic_adjusted_units'],0)

    def test_future_price_changes_do_not_change_past_targets_or_ledger(self):
        rows,ends=data();a=self.run_model(rows,ends,end=date(2000,1,31))
        for row in rows:
            if row['date']>date(2000,1,31):row.update(open=99999,close=99999,adjclose=99999)
        b=self.run_model(rows,ends,end=date(2000,1,31))
        self.assertEqual(a,b)

    def test_truncated_midmonth_is_not_treated_as_month_end(self):
        rows,ends=data();limit=date(1999,12,15)
        signals=monthly_targets([r for r in rows if r['date']<=limit],ends)
        self.assertEqual(max(signals),date(1999,11,30))

    def test_hold_matches_previous_cashflow_engine(self):
        rows,ends=data()
        a=simulate(rows,start=date(2000,1,1),end=date(2001,12,31),arm='IMMEDIATE',cash_mode='ZERO',cost_bps=5)
        b=self.run_model(rows,ends,arm='HOLD',cost_bps=5)
        for name in ('final_wealth','total_contributed','time_weighted_total_return','unitized_close_max_drawdown',
                     'money_weighted_annual_return','average_cash_weight'):
            self.assertEqual(a[name],b[name])
        self.assertEqual(b['sell_days'],0)

    def test_sell_friction_is_charged_and_no_negative_holdings(self):
        rows,ends=data()
        for row in rows:
            if row['date']>=date(2000,1,10):row.update(open=80,close=80,adjclose=80)
        a=self.run_model(rows,ends,cost_bps=0);b=self.run_model(rows,ends,cost_bps=5)
        self.assertGreater(b['sell_days'],0)
        self.assertTrue(all(f['friction']>0 for f in b['fills']))
        self.assertLess(b['final_wealth'],a['final_wealth'])
        self.assertTrue(all(x['cash']>=0 and x['synthetic_adjusted_units']>=0 for x in b['ledger']))

    def test_cash_regime_keeps_new_contributions_uninvested(self):
        rows,ends=data()
        for row in rows:row.update(open=100,close=100,adjclose=100)
        r=self.run_model(rows,ends)
        self.assertEqual(r['buy_days'],0);self.assertEqual(r['final_wealth'],r['total_contributed'])
        self.assertEqual(r['average_cash_weight'],1)

    def test_recovery_ignores_deposits_and_marks_censoring(self):
        r=recovery_stats([dict(date='2000-01-01',unit_nav=1,total=100),
                          dict(date='2000-01-02',unit_nav=.5,total=200),
                          dict(date='2000-01-04',unit_nav=1,total=400),
                          dict(date='2000-01-05',unit_nav=.9,total=500)])
        self.assertEqual(r['longest_completed_recovery_calendar_days'],3)
        self.assertTrue(r['unrecovered_at_end'])

    def test_lagged_cash_interest_and_same_contribution_budget(self):
        rows,ends=data()
        for row in rows:row.update(open=100,close=100,adjclose=100)
        rates=[(r['date'],.0365) for r in rows]
        r=self.run_model(rows,ends,cash_mode='TREASURY_PROXY',rates=rates)
        self.assertGreater(r['modeled_cash_interest'],0)
        self.assertAlmostEqual(r['final_wealth'],r['total_contributed']+r['modeled_cash_interest'])

    def test_missing_warmup_and_bad_prices_reject(self):
        rows,ends=data()
        with self.assertRaises(ValueError):self.run_model(rows,ends,start=date(1998,5,1))
        rows[-1]['adjclose']=float('nan')
        with self.assertRaises(ValueError):self.run_model(rows,ends)


if __name__=='__main__':unittest.main()
