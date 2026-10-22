import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import daily
from fixture import Scenario, SELECTORS

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Scenario(Path(self.tmp.name)/'SYNTHETIC');self.s.mark_until('2026-11-02')
        self.plans={s:[dict(symbol=self.s.cohort[0]['symbol'],sector='SECTOR-0')] for s in SELECTORS}
        self.p=dict(mode='SYNTHETIC_RD1',date='2026-11-03',received_at='2026-11-03T21:01:00Z',
                    action_review='SYNTHETIC_NO_UNMODELED_EVENTS',rank_mode='SYNTHETIC_RD1',plans=self.plans,
                    closes={self.s.cohort[0]['symbol']:'100'},anchor_closes={})
    def refs(self):
        return {k:dict(path=k,head_sha256=v.replay()[1]) for k,v in self.s.journals.items()}
    def run_day(self,p=None,refs=None):
        p=p or self.p
        return daily.apply(self.s.root,refs or self.refs(),p,p['received_at'])
    def test_entry_then_held_mark(self):
        self.assertEqual(self.run_day()['cases'],8)
        p=copy.deepcopy(self.p);p.update(date='2026-11-04',received_at='2026-11-04T21:01:00Z',anchor_date='2026-11-03',anchor_closes=dict(p['closes']))
        p['closes']={next(iter(p['closes'])):'101'}
        self.assertEqual(self.run_day(p)['cases'],8)
        for j in self.s.journals.values():self.assertEqual(daily.auditor.audit(j.root)['status'],'PASS')
    def test_stale_duplicate(self):
        refs=self.refs();self.run_day()
        with self.assertRaisesRegex(ValueError,'STALE'):self.run_day(refs=refs)
    def test_early_weekend_out_of_order(self):
        for day,time,reason in [('2026-11-03','2026-11-03T20:59:00Z','SESSION_NOT_CLOSED'),('2026-11-07','2026-11-07T23:00:00Z','NOT_XNYS_SESSION'),('2026-11-04','2026-11-04T23:00:00Z','NEXT_SESSION')]:
            p=copy.deepcopy(self.p);p.update(date=day,received_at=time)
            with self.assertRaisesRegex(ValueError,reason):self.run_day(p)
    def test_no_mutation_on_bad_inputs(self):
        before=self.refs()
        for field,value in [('mode','PRODUCTION'),('action_review','PENDING'),('closes',{})]:
            p=copy.deepcopy(self.p);p[field]=value
            with self.assertRaises(ValueError):self.run_day(p)
            self.assertEqual(before,self.refs())
    def test_basis_change_missing_anchor_and_held(self):
        self.run_day();before=self.refs()
        base=copy.deepcopy(self.p);base.update(date='2026-11-04',received_at='2026-11-04T21:01:00Z',anchor_date='2026-11-03',anchor_closes=dict(self.p['closes']))
        for change in [dict(anchor_closes={next(iter(self.p['closes'])):'50'}),dict(anchor_closes={}),dict(closes={})]:
            p=copy.deepcopy(base);p.update(change)
            with self.assertRaises(ValueError):self.run_day(p)
            self.assertEqual(before,self.refs())
    def test_partial_blocks_retry(self):
        original=daily.ledger.Journal.append;count=[0]
        def fail(j,request):
            count[0]+=1
            if count[0]==2:raise OSError('SYNTHETIC disk failure')
            return original(j,request)
        with patch.object(daily.ledger.Journal,'append',fail):
            with self.assertRaises(OSError):self.run_day()
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_OPERATION_NO_RETRY'):self.run_day()
        ops=list((self.s.root/'daily-operations').iterdir())
        self.assertEqual(len(json.loads((ops[0]/'partial.json').read_bytes())['confirmed']),1)

if __name__=='__main__':unittest.main()
