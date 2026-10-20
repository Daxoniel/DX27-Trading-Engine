from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audit_coverage_v2 import audit
from example import fixture
from strategy import canonical, scan as scan_v1
from strategy_v2 import scan as scan_v2


class CoverageAuditTests(unittest.TestCase):
    def artifacts(self, root):
        s = fixture()
        plans = dict(MLP1=scan_v1(s), MLP2=scan_v2(s))
        raw = canonical(dict(date='2025-10-20',plans=plans,excluded=[])).encode()
        (root/'day.gz').write_bytes(gzip.compress(raw))
        summary = dict(cohort_records=4,sessions=1,exclusions={},versions={},
            sessions_manifest=[dict(path='day.gz',sha256=sha256(raw).hexdigest())])
        for v,p in plans.items():
            counts = Counter(x['reason'] for x in p['rejected'])
            counts['WATCHLIST'] = len(p['watchlist'])
            summary['versions'][v] = dict(funnel=dict(counts),
                unique_symbols=len(p['watchlist']),sessions_with_candidates=int(bool(p['watchlist'])))
        (root/'summary.json').write_text(json.dumps(summary))
        return summary

    def test_reconstruct_and_detect_false_summary(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = self.artifacts(root)
            self.assertEqual(audit(root)['status'], 'PASS')
            summary['versions']['MLP2']['unique_symbols'] += 1
            (root/'summary.json').write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError,'SUMMARY_TOTAL_MISMATCH'):
                audit(root)

    def test_detect_modified_plan(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.artifacts(root)
            data = json.loads(gzip.decompress((root/'day.gz').read_bytes()))
            data['plans']['MLP2']['watchlist'].pop()
            (root/'day.gz').write_bytes(gzip.compress(canonical(data).encode()))
            with self.assertRaisesRegex(ValueError,'PLAN_DIGEST_MISMATCH'):
                audit(root)
