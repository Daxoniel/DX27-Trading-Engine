from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import guard as g
import test_evidence as fixtures

CLOCK=g.e.legacy.utc('2026-11-03T21:28:00+00:00')


class CommitTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.EvidenceTests('test_native_preopen_to_daily_is_read_only_and_alias_preserved')
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.capture();self.reviews=self.case.reviews();self.proposal=self.case.assess(self.reviews)
        self.root=self.case.s.root;self.original=self.case.bundle()
    def commit(self,proposal=None,proposal_hash=None,clock=lambda:CLOCK):
        proposal=self.proposal if proposal is None else proposal
        return g.commit(self.case.out,self.case.record,self.case.h,self.reviews,proposal,
                        g.e.digest(proposal) if proposal_hash is None else proposal_hash,clock)
    def op(self):
        return next((self.root/g.OPERATIONS).iterdir())
    def partial(self):
        return g.read_receipt(self.op()/'partial.json')[0]
    def assert_unchanged(self):
        self.assertEqual(self.original,self.case.bundle())
    def test_eight_case_entry_then_held_day_with_receipt_ancestry(self):
        result=self.commit()
        self.assertEqual(result['journal_writes'],8);self.assertFalse((self.root/g.LOCK).exists())
        self.assertFalse(result['atomic_multi_account_transaction']);self.assertEqual(result['orders'],0)
        self.case.out=self.case.root/'held-day'
        self.case.capture('2026-11-04',g.e.legacy.utc('2026-11-04T21:25:00+00:00'))
        self.reviews=self.case.reviews('2026-11-04T21:26:00+00:00')
        self.proposal=self.case.assess(self.reviews,'2026-11-04T21:27:00+00:00')
        result=self.commit(clock=lambda:g.e.legacy.utc('2026-11-04T21:28:00+00:00'))
        self.assertEqual(result['journal_writes'],8)
        self.assertEqual(len(list((self.root/g.OPERATIONS).iterdir())),2)
        for journal in self.case.s.journals.values():
            self.assertEqual(g.e.auditor.audit(journal.root)['status'],'PASS')
            self.assertEqual(journal.replay()[0]['marks'],4)
    def test_tampered_hash_injected_request_and_stale_duplicate(self):
        with self.assertRaisesRegex(ValueError,'PROPOSAL_FILE_HASH'):self.commit(proposal_hash='a'*64)
        self.assertFalse((self.root/g.LOCK).exists());self.assert_unchanged()
        forged=deepcopy(self.proposal);key=next(iter(forged['requests']))
        forged['requests'][key]['closes'][next(iter(forged['requests'][key]['closes']))]='1'
        with self.assertRaisesRegex(ValueError,'PROPOSAL_REVALIDATION_MISMATCH'):self.commit(forged)
        self.assert_unchanged();self.assertFalse((self.root/g.LOCK).exists())
        self.commit();after=self.case.bundle()
        with self.assertRaises(ValueError):self.commit()
        self.assertEqual(after,self.case.bundle());self.assertFalse((self.root/g.LOCK).exists())
    def test_exclusive_lock_and_owner_cannot_be_stolen(self):
        def attempt(_):
            try:return g.acquire(self.root,CLOCK)
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:tokens=list(pool.map(attempt,range(2)))
        winners=[t for t in tokens if t is not None];self.assertEqual(len(winners),1);token=winners[0]
        try:
            with self.assertRaisesRegex(ValueError,'WRITER_LOCK_PRESENT'):self.commit()
            with self.assertRaisesRegex(ValueError,'OWNERSHIP'):g.release(self.root,'NOT-OWNER')
            g.owned(self.root,token);self.assert_unchanged()
        finally:g.release(self.root,token)
    def test_after_write_exception_preserves_uncertain_case_and_blocks_retry(self):
        original=g.e.ledger.Journal.append;calls=[0]
        def failing(journal,request):
            event=original(journal,request);calls[0]+=1
            if calls[0]==2:raise OSError('SYNTHETIC failure after event reached disk')
            return event
        with patch.object(g.e.ledger.Journal,'append',failing):
            with self.assertRaises(OSError):self.commit()
        partial=self.partial();self.assertEqual(len(partial['confirmed_case_keys']),1)
        self.assertEqual(len(partial['attempted_case_keys']),2);self.assertTrue(partial['unconfirmed_writes_may_exist'])
        after=self.case.bundle()
        self.assertEqual(sum(after['heads'][k]!=self.original['heads'][k] for k in after['heads']),2)
        with self.assertRaisesRegex(ValueError,'WRITER_LOCK_PRESENT'):self.commit()
        # Simulate an external operator incorrectly removing only the fixture lock.
        shutil.rmtree(self.root/g.LOCK)
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_OPERATION_NO_RETRY'):self.commit()
        self.assertEqual(after,self.case.bundle());self.assertFalse((self.op()/'complete.json').exists())
    def test_prepared_receipt_disk_failure_leaves_lock_and_no_marks(self):
        original=g.write_receipt
        def failing(path,data):
            if Path(path).name=='prepared.json':raise OSError('SYNTHETIC disk full')
            return original(path,data)
        with patch.object(g,'write_receipt',failing):
            with self.assertRaises(OSError):self.commit()
        self.assert_unchanged();self.assertTrue((self.root/g.LOCK).exists())
        self.assertEqual(self.partial()['attempted_case_keys'],[])
    def test_source_mutation_during_revalidation_fails_without_append(self):
        original=g.e.assess
        def mutate(*args):
            result=original(*args);(self.case.out/'SYNTHETIC-DOC.txt').write_bytes(b'SYNTHETIC concurrent change')
            return result
        with patch.object(g.e,'assess',mutate):
            with self.assertRaisesRegex(ValueError,'EVIDENCE_CHANGED_DURING_COMMIT'):self.commit()
        self.assert_unchanged();self.assertFalse((self.root/g.LOCK).exists())
    def test_source_mutation_after_first_write_retains_partial(self):
        original=g.e.ledger.Journal.append;calls=[0]
        def mutate(journal,request):
            event=original(journal,request);calls[0]+=1
            if calls[0]==1:(self.case.out/'SYNTHETIC-DOC.txt').write_bytes(b'SYNTHETIC change after append')
            return event
        with patch.object(g.e.ledger.Journal,'append',mutate):
            with self.assertRaisesRegex(ValueError,'EVIDENCE_CHANGED_DURING_COMMIT'):self.commit()
        self.assertEqual(len(self.partial()['confirmed_case_keys']),1);self.assertTrue((self.root/g.LOCK).exists())
    def test_deadline_crossing_stops_before_next_append(self):
        calls=[0]
        def clock():
            calls[0]+=1
            return CLOCK if calls[0]<6 else g.e.legacy.utc('2026-11-04T14:30:00+00:00')
        with self.assertRaisesRegex(ValueError,'DAILY_CLOSE_WINDOW'):self.commit(clock=clock)
        self.assertEqual(len(self.partial()['confirmed_case_keys']),1)
        self.assertEqual(len(self.partial()['attempted_case_keys']),1)
    def test_postwrite_audit_failure_is_uncertain_not_rolled_back(self):
        original=g.e.auditor.audit
        def audit(root):
            result=original(root)
            if g.e.ledger.Journal(root).replay()[0]['marks']>2:result['status']='SYNTHETIC_FAIL'
            return result
        with patch.object(g.e.auditor,'audit',audit):
            with self.assertRaisesRegex(ValueError,'POSTCOMMIT_AUDIT_FAILED'):self.commit()
        self.assertEqual(self.partial()['confirmed_case_keys'],[])
        self.assertEqual(len(self.partial()['attempted_case_keys']),1);self.assertTrue((self.root/g.LOCK).exists())
    def test_completed_receipt_tampering_blocks_later_commit(self):
        self.commit();after=self.case.bundle()
        path=next(p for p in self.op().iterdir() if p.name not in ('prepared.json','complete.json'))
        value=json.loads(path.read_bytes());value['data']['after']='a'*64;path.write_bytes(g.e.canonical(value))
        with self.assertRaisesRegex(ValueError,'RECEIPT_HASH'):self.commit()
        self.assertEqual(after,self.case.bundle())
    def test_lost_completed_event_blocks_even_when_remaining_journal_replays(self):
        self.commit()
        journal=next(iter(self.case.s.journals.values()))
        last=sorted(journal.root.iterdir())[-1];last.unlink()
        journal.replay() # A valid shorter journal alone cannot certify completed writes.
        with self.assertRaisesRegex(ValueError,'COMPLETED_HEAD_NOT_ANCESTOR'):self.commit()
        self.assertFalse((self.root/g.LOCK).exists())
    def test_early_clock_never_reads_supplied_inputs_or_creates_lock(self):
        result=g.commit(None,None,None,None,None,None,lambda:g.e.legacy.utc('2026-10-22T12:00:00+00:00'))
        self.assertEqual(result['status'],'BLOCKED_FORMATION_NOT_CLOSED')
        self.assertFalse(result['lock_created']);self.assertEqual(result['journal_writes'],0)
        self.assert_unchanged();self.assertFalse((self.root/g.LOCK).exists())


if __name__=='__main__':unittest.main()
