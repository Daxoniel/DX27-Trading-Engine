import unittest
from decimal import Decimal as D
from paper_basis import fixed_fill_views,operational_scope


class PaperBasisTests(unittest.TestCase):
    def arm(self):
        return dict(gross_pnl=100,commission=10,spread_cost=20,slippage_cost=30,
                    net_pnl=40,reference_turnover=100000)

    def test_commission_credit_does_not_remove_friction(self):
        r=fixed_fill_views(self.arm())
        self.assertEqual(r['no_broker_commission_with_old_price_friction_pnl'],D(50))
        self.assertEqual(r['no_explicit_cost_reference_price_pnl'],D(100))
        self.assertIsNone(r['actual_alpaca_paper_pnl'])

    def test_all_extra_friction_cases_retained(self):
        r=fixed_fill_views(self.arm())
        self.assertEqual([v['additional_bps'] for v in r['fixed_fill_extra_friction']],[0,1,2,5])
        self.assertEqual(r['fixed_fill_extra_friction'][-1]['pnl'],D(0))
        self.assertFalse(r['capital_and_size_recomputed'])

    def test_bad_or_nonfinite_accounting_rejected(self):
        for delta in ({'net_pnl':41},{'commission':-1},{'gross_pnl':'NaN'}):
            a=self.arm();a.update(delta)
            with self.assertRaises(ValueError):fixed_fill_views(a)

    def sample(self):
        return dict(mode='PAPER_GET_ONLY_SAMPLE',execution_enabled=False,real_orders_sent=False,
            evidence_complete=False,history_complete=False,sampling_complete=True,
            endpoints=dict(activities=dict(status='OBSERVED',sample_count=0)))

    def test_empty_samples_do_not_prove_fees_or_performance(self):
        r=operational_scope(self.sample())
        self.assertIsNone(r['actual_strategy_paper_pnl']);self.assertFalse(r['verified_zero_fees'])
        self.assertFalse(r['history_complete'])

    def test_non_paper_or_mutating_observation_rejected(self):
        for delta in ({'mode':'LIVE'},{'real_orders_sent':True},{'history_complete':True}):
            s=self.sample();s.update(delta)
            with self.assertRaises(ValueError):operational_scope(s)

    def test_incomplete_sample_not_promoted(self):
        s=self.sample();s['sampling_complete']=False
        self.assertFalse(operational_scope(s)['sampling_complete'])


if __name__=='__main__':unittest.main()
