import io
import json
from pathlib import Path
import unittest
import zipfile
from prepare import allocation, factor_months, report, required_months, ROOT


def archive(lines):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('f.csv', '\n'.join(lines))
    return out.getvalue()


class PreparationTests(unittest.TestCase):
    def test_budget_never_redistributes_empty_slots(self):
        rows = [dict(symbol=str(i), sector=str(i//2)) for i in range(10)]
        full = allocation(100000, rows)
        self.assertEqual(full['target_stock_notional_before_costs_usd'], '10000.00')
        self.assertEqual(allocation(100000, rows[:3])['cash_before_costs_usd'], '97000.00')
        self.assertFalse(full['executable'])
        for bad in ('NaN', 'Infinity', 0, -1):
            with self.assertRaises(ValueError): allocation(bad, [])

    def test_identity_duplicates_sector_and_reserved_symbol_block(self):
        for rows in ([dict(symbol='SOXL',sector='A')],
                     [dict(symbol='A',sector='A')]*2,
                     [dict(symbol=str(i),sector='A') for i in range(3)]):
            with self.assertRaises(ValueError): allocation(100, rows)

    def test_exact_factor_window_and_annual_rows_ignored(self):
        months = required_months()
        self.assertEqual((len(months), months[0], months[-1]), (36,'2023-10','2026-09'))
        data = archive([m.replace('-','')+',1,2,3,4' for m in months]+['2026,1,2,3,4'])
        self.assertEqual(factor_months(data), set(months))
        with self.assertRaises(ValueError): factor_months(archive(['202609,NaN,2,3,4']))
        with self.assertRaises(ValueError): factor_months(archive(['202609,1,2,3,4']*2))

    def test_complete_factors_cannot_promote_or_fake_future_observation(self):
        window = dict(formation='2026-10-30', execution='2026-11-03',
                      formation_close='2026-10-30T20:00:00+00:00', execution_open='2026-11-03T14:30:00+00:00')
        protocol = (ROOT/'docs/research/residual-forward/protocol.json').read_bytes()
        blob = archive([m.replace('-','')+',1,2,3,4' for m in required_months()])
        early = report(blob,'2026-10-21T12:00:00+00:00',window,protocol)
        self.assertIn('FORMATION_NOT_CLOSED', early['blockers'])
        timely = report(blob,'2026-11-02T12:00:00+00:00',window,protocol)
        self.assertEqual(timely['status'], 'BLOCKED_PREPARATION_ONLY')
        self.assertFalse(timely['signal_computed']); self.assertEqual(timely['orders_sent'],0)
        late = report(blob,'2026-11-03T14:30:00+00:00',window,protocol)
        self.assertIn('CYCLE_DEADLINE_MISSED', late['blockers'])
        missing = report(archive(['202608,1,2,3,4']),'2026-10-21T12:00:00+00:00',window,protocol)
        self.assertIn('2026-09',missing['factor_receipt']['missing_required_months'])
        self.assertIn('FACTOR_MONTHS_MISSING',missing['blockers'])


if __name__ == '__main__': unittest.main()
