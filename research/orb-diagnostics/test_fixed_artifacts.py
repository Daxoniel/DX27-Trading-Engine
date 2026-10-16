import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal as D
from fixed_artifacts import aggregate, load, reconstruct


def fill(side, reference, price, fee, at, reason, spread='0', slip='0'):
    q = 10
    signed = q if side == 'buy' else -q
    return dict(side=side, quantity=q, reference=D(reference), price=D(price), commission=D(fee),
                at=at, reason=reason, spread_cost=D(spread), slippage_cost=D(slip),
                cash_delta=-signed*D(price)-D(fee))


def pair(profile='R0', short=False):
    sides = ('sell', 'buy') if short else ('buy', 'sell')
    if profile == 'R0':
        return (fill(sides[0], '100', '100', '.005', '2026-07-01T13:35:00+00:00', 'ENTRY'),
                fill(sides[1], '110', '110', '.005', '2026-07-01T14:00:00+00:00', 'TARGET'))
    return (fill('buy', '100', '100.02', '.35', '2026-07-01T13:36:00+00:00', 'ENTRY', '.1', '.1'),
            fill('sell', '110', '109.978', '.35', '2026-07-01T14:00:00+00:00', 'TARGET', '.11', '.11'))


class DiagnosticTests(unittest.TestCase):
    def test_long_and_short_cash_sign(self):
        self.assertEqual(reconstruct(*pair(), 'R0')['net_pnl'], D('99.990'))
        r = reconstruct(*pair(short=True), 'R0')
        self.assertEqual(r['net_pnl'], D('-100.010'))
        self.assertEqual(r['direction'], 'short')

    def test_model_cost_and_minimum_fee(self):
        r = reconstruct(*pair('R1'), 'R1')
        self.assertEqual(r['gross_pnl'], D('100'))
        self.assertEqual(r['net_pnl'], D('98.88'))
        self.assertEqual(r['minimum_commission_fills'], 2)
        self.assertEqual(aggregate([r])['total_cost'], D('1.12'))

    def test_no_trade_means_are_null(self):
        r = aggregate([])
        self.assertIsNone(r['mean_net_pnl'])
        self.assertIsNone(r['modeled_cost_bps'])

    def test_cost_can_turn_winner_into_loss(self):
        r = reconstruct(*pair(), 'R0')
        r.update(gross_pnl=D('.005'), net_pnl=D('-.005'))
        self.assertEqual(aggregate([r])['gross_positive_net_nonpositive'], 1)

    def test_reject_unclosed_inventory(self):
        a, b = pair(); b['quantity'] = 9
        with self.assertRaisesRegex(ValueError, 'FILL_QUANTITY'):
            reconstruct(a, b, 'R0')

    def test_reject_cash_corruption(self):
        a, b = pair(); b['cash_delta'] += 1
        with self.assertRaisesRegex(ValueError, 'ACCOUNTING_MISMATCH'):
            reconstruct(a, b, 'R0')

    def test_reject_reversed_clock(self):
        a, b = pair(); b['at'] = '2026-07-01T12:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'FILL_CLOCK'):
            reconstruct(a, b, 'R0')

    def test_reject_duplicate_or_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'input.json'
            for text in ('{"x":1,"x":2}', '{"x":NaN}'):
                p.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    load(p)


if __name__ == '__main__':
    unittest.main()
