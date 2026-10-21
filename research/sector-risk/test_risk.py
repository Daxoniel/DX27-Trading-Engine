from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import unittest

from study import forecast, make_plans, parent, run, scale_for
from audit import audit_case, independent_forecast

PUBLIC = Path(__file__).resolve().parents[2]/'docs/research'
RULES = json.loads((PUBLIC/'sector-risk/protocol.json').read_text())
ORIGINAL = json.loads((PUBLIC/'sector-momentum/protocol.json').read_text())


def fixture():
    calendar = []; day = date(2024, 1, 1)
    while day <= date(2025, 12, 31):
        if day.weekday() < 5:
            calendar.append(day.isoformat())
        day += timedelta(days=1)
    adj = {'A': {}, 'B': {}}; prices = {'A': 100., 'B': 100.}
    for i, day in enumerate(calendar):
        for s in prices:
            shock = (.04 if i % 2 else -.032) * (1 if day < '2025-05-01' else 3)
            prices[s] *= 1+shock*(1 if s == 'A' else 1.5)
            adj[s][day] = prices[s]
    formations = [dict(asof=day, eligible=[dict(symbol='A', sector='X', beta=2., momentum=1., relative=1.),
                    dict(symbol='B', sector='Y', beta=3., momentum=2., relative=2.)])
                  for day in ['2025-04-30', '2025-05-30']]
    return adj, calendar, formations


class RiskTests(unittest.TestCase):
    def test_rms_does_not_demean_constant_returns(self):
        adj, cal, forms = fixture(); price = 100.
        for day in cal:
            price *= 1.01; adj['A'][day] = price
        vol = forecast(adj, cal, forms[0]['asof'], {'A': 1.}, RULES)
        self.assertAlmostEqual(vol, .01*math.sqrt(252))
        independent, _ = independent_forecast(adj, cal, forms[0]['asof'], {'A': Decimal(1)}, RULES)
        self.assertAlmostEqual(vol, float(independent))

    def test_square_of_basket_return_includes_cross_terms(self):
        adj, cal, forms = fixture()
        vol_a = forecast(adj, cal, forms[0]['asof'], {'A': 1.}, RULES)
        adj['B'] = deepcopy(adj['A'])
        self.assertAlmostEqual(forecast(adj, cal, forms[0]['asof'], {'A': .5, 'B': .5}, RULES), vol_a)

    def test_future_prices_cannot_change_formation_risk_plan(self):
        adj, cal, forms = fixture()
        expected = make_plans(adj, cal, forms[:1], 'ordinary', 'monthly_risk', ORIGINAL, RULES)
        for rows in adj.values():
            for day in rows:
                if day > forms[0]['asof']:
                    rows[day] *= 100
        self.assertEqual(expected, make_plans(adj, cal, forms[:1], 'ordinary', 'monthly_risk', ORIGINAL, RULES))

    def test_exact_126_returns_and_missing_history_rejected(self):
        adj, cal, forms = fixture(); asof = forms[0]['asof']; index = cal.index(asof)
        with self.assertRaisesRegex(ValueError, 'TOO_SHORT'):
            forecast(adj, cal[index-125:], asof, {'A': 1.}, RULES)
        adj['A'].pop(cal[index-126])
        with self.assertRaisesRegex(ValueError, 'HISTORY_MISSING'):
            forecast(adj, cal, asof, {'A': 1.}, RULES)

    def test_unit_cap_zero_and_invalid_forecast(self):
        self.assertEqual(scale_for(.01, RULES), 1)
        self.assertEqual(scale_for(0, RULES), 1)
        self.assertAlmostEqual(scale_for(.6, RULES), .2)
        for value in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                scale_for(value, RULES)

    def test_fixed_initial_scale_is_not_refitted_to_later_forecasts(self):
        adj, cal, forms = fixture()
        fixed = make_plans(adj, cal, forms, 'ordinary', 'fixed_initial', ORIGINAL, RULES)
        dynamic = make_plans(adj, cal, forms, 'ordinary', 'monthly_risk', ORIGINAL, RULES)
        self.assertEqual(fixed[0]['scale'], fixed[1]['scale'])
        self.assertGreater(dynamic[0]['scale'], dynamic[1]['scale'])
        self.assertEqual(fixed[0]['scale'], dynamic[0]['scale'])

    def test_unmanaged_reproduces_parent_path_and_lag(self):
        adj, cal, forms = fixture()
        plans = make_plans(adj, cal, forms, 'ordinary', 'unmanaged', ORIGINAL, RULES)
        case = run(adj, cal, plans, 25, ORIGINAL)
        previous = parent.run(adj, cal, forms, 'ordinary', 25, ORIGINAL)
        self.assertEqual(case['nav'], previous['nav'])
        self.assertEqual(case['events'][0]['date'], '2025-05-02')
        self.assertEqual(case['nav'][0]['equity'], ORIGINAL['initial_proxy_capital'])

    def test_scaled_costs_and_cash_reconcile_and_tamper_is_detected(self):
        adj, cal, forms = fixture()
        plans = make_plans(adj, cal, forms, 'ordinary', 'monthly_risk', ORIGINAL, RULES)
        case = run(adj, cal, plans, 25, ORIGINAL)
        audit = lambda c: audit_case(c, adj, cal, forms, 'ordinary', 'monthly_risk', 25, ORIGINAL, RULES)
        self.assertEqual(audit(case)['status'], 'PASS')
        for field in ('new_cash', 'cost', 'turnover_notional'):
            changed = deepcopy(case); changed['events'][1][field] += 1
            with self.assertRaisesRegex(ValueError, 'RECONCILIATION'):
                audit(changed)
        self.assertTrue(all(n['cash'] >= 0 for n in case['nav']))

    def test_missing_held_price_halts_and_blocks_complete_audit(self):
        adj, cal, forms = fixture()
        plans = make_plans(adj, cal, forms, 'ordinary', 'monthly_risk', ORIGINAL, RULES)
        adj['A'].pop('2025-05-05')
        case = run(adj, cal, plans, 5, ORIGINAL)
        self.assertIsNone(case['summary']['proxy_return'])
        with self.assertRaisesRegex(ValueError, 'FULL_PERIOD'):
            audit_case(case, adj, cal, forms, 'ordinary', 'monthly_risk', 5, ORIGINAL, RULES)

    def test_empty_basket_stays_cash(self):
        adj, cal, forms = fixture()
        for f in forms:
            f['eligible'] = []
        plans = make_plans(adj, cal, forms, 'relative', 'monthly_risk', ORIGINAL, RULES)
        case = run(adj, cal, plans, 5, ORIGINAL)
        self.assertEqual(case['summary']['proxy_return'], 0)
        self.assertEqual(case['summary']['modeled_cost'], 0)
        self.assertEqual(audit_case(case, adj, cal, forms, 'relative', 'monthly_risk', 5, ORIGINAL, RULES)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
