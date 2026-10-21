from copy import deepcopy
from datetime import date
from hashlib import sha256
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from validation import IntegrityError, join_forward, quarantine_forward, read_batches, read_factors, rm, screen


def cases():
    result = {}
    for bps in (5,25):
        for name in ('matched_ordinary','matched_residual'):
            better = name=='matched_residual'
            result[f'{name}-{bps}bp'] = dict(summary=dict(halt=None,proxy_return=.1 if better else .05,
                observed_daily_drawdown=.2 if better else .3,
                stock_return_intervals=90,positive_stock_return_intervals=54 if better else 45))
    return result


def factor_zip(extra=''):
    lines = ['metadata',',Mkt-RF,SMB,HML,RF']
    for i in range(44):
        month = rm.parent.shift_month(date(2022,12,1),i).replace('-','')
        lines.append(month+',1.0,2.0,-3.0,0.1')
    lines += ['2026,999,999,999,999','202608,999,999,999,999',extra]
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w') as archive:
        archive.writestr('ff.csv','\n'.join(lines))
    return out.getvalue()


class ValidationTests(unittest.TestCase):
    def test_forward_seam_is_exact_and_parent_is_not_mutated(self):
        old = {'A':{'2025-12-31':10.}}
        new = {'A':{'2025-12-31':10.,'2026-01-02':11.}}
        joined, count = join_forward(old,new)
        self.assertEqual(count,1); self.assertEqual(joined['A']['2026-01-02'],11.)
        self.assertNotIn('2026-01-02',old['A'])
        new['A']['2025-12-31'] += .00000001
        with self.assertRaises(IntegrityError):
            join_forward(old,new)

    def test_raw_volume_revision_or_date_coverage_change_also_blocks(self):
        old = {'A':{'2025-12-31':(10.,100)}}
        for new in ({'A':{'2025-12-31':(10.,101)}},{'A':{'2026-01-02':(10.,100)}}):
            with self.assertRaises(IntegrityError):
                join_forward(old,new)

    def test_reserved_symbol_is_rejected_in_decoded_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); raw = json.dumps({'SOXL':[]}).encode()
            (path/'batch.gz').write_bytes(gzip.compress(raw))
            with self.assertRaisesRegex(ValueError,'RESERVED_SYMBOL'):
                read_batches(path,[dict(path='batch.gz',sha256=sha256(raw).hexdigest())])

    def test_factor_range_units_and_future_rows(self):
        factors = read_factors(factor_zip())
        self.assertEqual(len(factors),44)
        self.assertEqual(factors['2026-07'],[.01,.02,-.03,.001])
        self.assertNotIn('2026-08',factors)
        with self.assertRaisesRegex(ValueError,'INVALID_FACTOR'):
            read_factors(factor_zip('202607,1,2,3,4'))

    def test_pass_never_promotes_and_stress_cost_failure_is_not_hidden(self):
        runs = cases(); self.assertEqual(screen(runs)['status'],'PASS')
        self.assertFalse(screen(runs)['automatic_promotion'])
        runs['matched_residual-25bp']['summary']['proxy_return'] = -.01
        self.assertEqual(screen(runs)['status'],'FAIL')

    def test_each_drawdown_frequency_and_return_gate_matters(self):
        for field,value in [('observed_daily_drawdown',.26),('positive_stock_return_intervals',44),('proxy_return',.04)]:
            runs = cases(); runs['matched_residual-5bp']['summary'][field] = value
            self.assertEqual(screen(runs)['status'],'FAIL')

    def test_halt_or_missing_primary_return_means_incomplete(self):
        for name in ('matched_ordinary-5bp','matched_residual-25bp'):
            runs = cases(); runs[name]['summary'].update(halt=dict(date='2026-02-01'),proxy_return=None)
            self.assertEqual(screen(runs)['status'],'INCOMPLETE')

    def test_signal_keeps_full_month_factor_lag_in_new_year(self):
        import math
        factors = {}; prices = {'A':{'2022-11-28':100.}}; calendar = ['2022-11-28']; value = 100.
        for i in range(44):
            month = rm.parent.shift_month(date(2022,12,1),i)
            f = [.02*math.sin(i*.4),.03*math.cos(i*.7),.015*math.sin(i*.3),.001]
            factors[month] = f
            value *= 1+.015+f[3]+2*f[0]+.5*f[1]-.3*f[2]+.01*math.sin(i*1.1)
            day = month+'-28'; prices['A'][day] = value; calendar.append(day)
        rules = json.loads((Path(__file__).resolve().parents[2]/'docs/research/residual-momentum/protocol.json').read_text())
        before = rm.score('A','2026-01-28',prices,calendar,factors,rules)
        self.assertEqual(before['fit_end'],'2025-12')
        for month in factors:
            if month>='2026-01':
                factors[month] = [10.,10.,10.,1.]
                prices['A'][month+'-28'] *= 100
        self.assertEqual(before,rm.score('A','2026-01-28',prices,calendar,factors,rules))

    def test_forward_quarantine_requires_past_ineligibility_for_every_formation(self):
        from datetime import timedelta
        calendar=[]; day=date(2025,1,1)
        while day<=date(2027,2,1):
            if day.weekday()<5:
                calendar.append(day.isoformat())
            day+=timedelta(days=1)
        old={'A':{'2025-11-28':10.},'B':{'2025-12-31':20.}}
        new={'A':{'2025-12-31':11.,'2026-01-02':12.},'B':{'2025-12-31':21.}}
        filtered,blocked,proof=quarantine_forward(old,new,calendar,['2025-12-31','2026-08-31'])
        self.assertEqual(blocked,['A']); self.assertEqual(filtered['A'],{})
        self.assertTrue(all(r['minimum_old_missing_beta_window_sessions']>0 for r in proof))
        self.assertEqual(old['A'],{'2025-11-28':10.})
        with self.assertRaises(IntegrityError):
            join_forward(old,filtered)  # B price mismatch is never waived.
        with self.assertRaisesRegex(ValueError,'COULD_CHANGE_ELIGIBILITY'):
            quarantine_forward(old,new,calendar,['2027-01-29'])


if __name__=='__main__':
    unittest.main()
