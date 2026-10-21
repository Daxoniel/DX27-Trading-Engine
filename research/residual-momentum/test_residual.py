from copy import deepcopy
import io
import json
import math
from pathlib import Path
import unittest
import zipfile

from audit import independent_score, verify
from features import fit_qr, month_shift, parse_factors, score
from runner import adapt, extend_prices, parent

RULES = json.loads((Path(__file__).resolve().parents[2]/'docs/research/residual-momentum/protocol.json').read_text())


def fixture(alpha=.015):
    factors = {}; prices = {'A': {'2022-03-28': 100.}}; calendar = ['2022-03-28']; value = 100.
    for i in range(43):
        month = month_shift('2022-04', i)
        f = [.02*math.sin(i*.4), .03*math.cos(i*.7), .015*math.sin(i*.3), .001]
        factors[month] = f
        r = f[3]+alpha+2*f[0]+.5*f[1]-.3*f[2]+.01*math.sin(i*1.1)
        value *= 1+r; day = month+'-28'; prices['A'][day] = value; calendar.append(day)
    return prices, calendar, factors


def zip_csv(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('ff.csv', text)
    return out.getvalue()


class ResidualTests(unittest.TestCase):
    def test_qr_fits_intercept_and_three_factors(self):
        _, _, factors = fixture(); x = [[1, *row[:3]] for row in list(factors.values())[:36]]
        expected = [.02, 2., -.5, .3]
        y = [sum(a*b for a, b in zip(row, expected)) for row in x]
        for a, b in zip(fit_qr(x, y), expected):
            self.assertAlmostEqual(a, b, places=11)

    def test_singular_factor_columns_rejected_without_regularization(self):
        with self.assertRaisesRegex(ValueError, 'SINGULAR'):
            fit_qr([[1, i, i, 2*i] for i in range(36)], list(range(36)))

    def test_decimal_reconstruction_matches_qr_score(self):
        prices, cal, factors = fixture()
        primary = score('A', '2025-04-28', prices, cal, factors, RULES)
        verify(primary, independent_score('A', '2025-04-28', prices, cal, factors))
        self.assertEqual((primary['fit_start'], primary['fit_end']), ('2022-04', '2025-03'))
        self.assertEqual((primary['rank_start'], primary['rank_end']), ('2024-05', '2025-03'))
        self.assertEqual(primary['fit_months'], 36); self.assertEqual(primary['rank_months'], 11)

    def test_alpha_fitted_but_not_subtracted_from_ranking_returns(self):
        prices, cal, factors = fixture()
        first = score('A', '2025-04-28', prices, cal, factors, RULES)
        changed, _, _ = fixture(alpha=.025)
        second = score('A', '2025-04-28', changed, cal, factors, RULES)
        for a, b in zip(first['coefficients'][1:], second['coefficients'][1:]):
            self.assertAlmostEqual(a, b, places=10)
        self.assertAlmostEqual(second['coefficients'][0]-first['coefficients'][0], .01)
        self.assertAlmostEqual(second['score']-first['score'], .11/first['dispersion'])
        self.assertAlmostEqual(sum(first['factor_adjusted_returns'])/36, first['coefficients'][0])

    def test_formation_month_and_future_factors_cannot_change_score(self):
        prices, cal, factors = fixture()
        expected = score('A', '2025-04-28', prices, cal, factors, RULES)
        for day in prices['A']:
            if day >= '2025-04-01':
                prices['A'][day] *= 100
        for month in factors:
            if month >= '2025-04':
                factors[month] = [10., 20., 30., 1.]
        self.assertEqual(expected, score('A', '2025-04-28', prices, cal, factors, RULES))

    def test_missing_monthly_stock_or_factor_input_never_filled(self):
        prices, cal, factors = fixture(); prices['A'].pop('2022-03-28')
        with self.assertRaisesRegex(ValueError, 'STOCK_HISTORY_MISSING'):
            score('A', '2025-04-28', prices, cal, factors, RULES)
        prices, cal, factors = fixture(); factors.pop('2024-06')
        with self.assertRaisesRegex(ValueError, 'FACTOR_HISTORY_MISSING'):
            score('A', '2025-04-28', prices, cal, factors, RULES)

    def test_percent_once_annual_rows_and_future_dates_ignored(self):
        rows = ['Metadata', ',Mkt-RF,SMB,HML,RF']
        rows += [month_shift('2022-04', i).replace('-', '')+',1.0,2.0,-3.0,0.1' for i in range(43)]
        rows += ['2025,100,100,100,100', '202601,999,999,999,999']
        factors = parse_factors(zip_csv('\n'.join(rows)))
        self.assertEqual(len(factors), 43)
        self.assertEqual(factors['2022-04'], [.01, .02, -.03, .001])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            parse_factors(zip_csv('\n'.join(rows+['202204,1,2,3,4'])))
        with self.assertRaisesRegex(ValueError, 'COVERAGE'):
            parse_factors(zip_csv('\n'.join(rows[:3])))

    def test_zero_dispersion_never_becomes_infinite_score(self):
        prices, cal, factors = fixture(); value = 100.; prices['A']['2022-03-28'] = value
        for month, f in factors.items():
            value *= 1+f[3]+.02+2*f[0]+.5*f[1]-.3*f[2]
            prices['A'][month+'-28'] = value
        with self.assertRaisesRegex(ValueError, 'DISPERSION'):
            score('A', '2025-04-28', prices, cal, factors, RULES)

    def test_vintage_overlap_mismatch_blocks_history_splice(self):
        old = {'A': {'2023-01-03': 10., '2023-02-01': 12.}}
        extension = {'A': [{'t': '2022-12-30T00:00:00Z', 'c': 9.}, {'t': '2023-01-03T00:00:00Z', 'c': 10.}]}
        joined, count = extend_prices(old, extension)
        self.assertEqual(count, 1); self.assertEqual(joined['A']['2022-12-30'], 9.)
        self.assertNotIn('2022-12-30', old['A'])
        extension['A'][1]['c'] = 11.
        with self.assertRaisesRegex(ValueError, 'VINTAGE_OVERLAP'):
            extend_prices(old, extension)

    def test_matched_controls_share_pool_without_mutating_parent(self):
        original = [dict(asof='2025-04-30', eligible=[dict(symbol='A', sector='X', momentum=2., relative=1.),
                    dict(symbol='B', sector='Y', momentum=3., relative=2.)])]
        matched = deepcopy(original); matched[0]['eligible'].pop()
        matched[0]['eligible'][0]['residual_feature'] = dict(score=-1.)
        for selector in ('matched_ordinary', 'matched_relative', 'matched_residual'):
            adapted = adapt(original, matched, selector)
            self.assertEqual([r['symbol'] for r in adapted[0]['eligible']], ['A'])
        self.assertEqual(original[0]['eligible'][0]['momentum'], 2.)
        self.assertEqual(len(adapt(original, matched, 'parent_ordinary')[0]['eligible']), 2)
        self.assertEqual(adapt(original, matched, 'matched_residual')[0]['eligible'][0]['momentum'], -1.)

    def test_independent_audit_rejects_score_or_window_tamper(self):
        prices, cal, factors = fixture()
        first = score('A', '2025-04-28', prices, cal, factors, RULES)
        other = independent_score('A', '2025-04-28', prices, cal, factors)
        for field, value in [('score', first['score']+1), ('fit_end', '2025-04')]:
            changed = deepcopy(first); changed[field] = value
            with self.assertRaises(ValueError):
                verify(changed, other)


if __name__ == '__main__':
    unittest.main()
