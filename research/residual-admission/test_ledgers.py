from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import exchange_calendars as xc

import admission
from snapshots import utc


class LedgerAdmissionTests(unittest.TestCase):
    def test_actual_eight_initial_heads_verified_and_tampering_blocks(self):
        rows=json.loads((admission.ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles']
        cal=xc.get_calendar('XNYS')
        days=[s.date().isoformat() for s in cal.sessions_in_range(rows[0]['formation'],'2027-04-30')]
        ledger=admission.load('ra_fixture_ledger','research/residual-shadow/ledger.py')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);refs={}
            for selector in ('parent_ordinary','matched_ordinary','matched_relative','matched_residual'):
                for bps in (5,25):
                    key=f'{selector}-{bps}bp';j=ledger.Journal(root/key)
                    j.create(ledger.initialize(days,[r['execution'] for r in rows],bps))
                    refs[key]=dict(path=key,head_sha256=j.replay()[1])
            self.assertEqual(admission.verified_holdings(root,refs,utc('2026-11-02T12:00:00+00:00'),rows),set())
            bad=deepcopy(refs);bad['matched_residual-5bp']['head_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'LEDGER_HEAD_OR_HALT'):
                admission.verified_holdings(root,bad,utc('2026-11-02T12:00:00+00:00'),rows)
            bad=deepcopy(refs);bad['matched_residual-5bp']['path']='../outside'
            with self.assertRaisesRegex(ValueError,'LEDGER_PATH'):
                admission.verified_holdings(root,bad,utc('2026-11-02T12:00:00+00:00'),rows)
            key='parent_ordinary-5bp';j=ledger.Journal(root/key)
            j.append(dict(date=days[0],closes={},source_sha256='a'*64))
            refs[key]['head_sha256']=j.replay()[1]
            with self.assertRaisesRegex(ValueError,'LEDGER_FUTURE_MARK'):
                admission.verified_holdings(root,refs,utc('2026-10-21T12:00:00+00:00'),rows)


if __name__=='__main__': unittest.main()
