import unittest
from decimal import Decimal as D
from cause_audit import sizing_caps, delay_components, affordable
from test_fixed_artifacts import fill


def trade(side,entry,exit_,quantity=10):
    opposite='sell' if side=='buy' else 'buy'
    a=fill(side,entry,entry,'.005','2026-07-01T13:35:00+00:00','ENTRY')
    b=fill(opposite,exit_,exit_,'.005','2026-07-01T14:00:00+00:00','STOP')
    for f in (a,b):
        f['quantity']=quantity
        f['commission']=D(quantity)*D('.0005')
        signed=quantity if f['side']=='buy' else -quantity
        f['cash_delta']=-signed*f['price']-f['commission']
    return [a,b]


class CauseTests(unittest.TestCase):
    def test_nominal_binds_narrow_stop(self):
        x=sizing_caps(100000.,100.,99.9,1000000.)
        self.assertEqual(x['quantity'],249)
        self.assertEqual(x['binding'],['nominal'])
        self.assertLess(x['planned_risk_pct'],.25)

    def test_volume_binds(self):
        self.assertEqual(sizing_caps(100000.,100.,99.9,100.)['binding'],['volume'])

    def test_risk_binds_wide_stop(self):
        self.assertEqual(sizing_caps(100000.,100.,90.,1000000.)['binding'],['risk'])

    def test_binary_boundary(self):
        self.assertEqual(affordable(20,lambda q:q*3<=31),10)

    def test_reject_nonpositive_r(self):
        with self.assertRaises(ValueError):sizing_caps(100000.,100.,100.,100.)

    def test_long_entry_component_identity(self):
        x=delay_components({'d':trade('buy','100','110')},{'d':trade('buy','101','110')})
        self.assertEqual(x['components_usd']['entry_price'],D('-10'))
        self.assertEqual(x['total_net_delta_usd'],D('-10'))
        self.assertEqual(x['counts']['adverse_entry'],1)

    def test_short_entry_and_exit_identity(self):
        x=delay_components({'d':trade('sell','100','90')},{'d':trade('sell','99','91')})
        self.assertEqual(x['components_usd']['entry_price'],D('-10'))
        self.assertEqual(x['components_usd']['exit_price'],D('-10'))
        self.assertEqual(x['total_net_delta_usd'],D('-20'))

    def test_quantity_capital_and_commission_identity(self):
        x=delay_components({'d':trade('buy','100','110',10)},
                           {'d':trade('buy','101','111',20)})
        self.assertEqual(x['components_usd']['entry_price'],D('-10'))
        self.assertEqual(x['components_usd']['exit_price'],D('10'))
        self.assertEqual(x['components_usd']['quantity_and_capital'],D('100'))
        self.assertEqual(x['components_usd']['commission'],D('-.01'))
        self.assertEqual(x['total_net_delta_usd'],D('99.99'))

    def test_removed_trade_preserved(self):
        x=delay_components({'d':trade('buy','100','110')},{})
        self.assertEqual(x['counts']['removed'],1)
        self.assertEqual(x['components_usd']['removed_reference_trades'],D('-99.99'))


if __name__=='__main__':unittest.main()
