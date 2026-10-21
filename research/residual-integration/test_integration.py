from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fixture import Scenario,artifact
from transition import admission,apply,ledger
from snapshots import canonical


class NonemptyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.scenario=Scenario(Path(self.temp.name)/'SYNTHETIC')
        self.scenario.mark_until('2026-11-02')
        self.bundle=self.scenario.bundle(0)

    def execute(self,bundle=None):
        manifest,packet,admitted,observed,_=bundle or self.bundle
        with self.scenario.cohort_boundary():
            return apply(self.scenario.root,manifest,packet,admitted,observed)

    def test_nonempty_two_cycles_existing_holdings_exit_and_independent_audit(self):
        manifest,packet,admitted,observed,calculated=self.bundle
        self.assertEqual(calculated['independently_checked_scores'],55)
        self.assertTrue(all(len(rows)==10 for rows in calculated['plans'].values()))
        first=self.execute();self.assertEqual(first['cases'],8)
        previous={k:set(j.replay()[0]['units']) for k,j in self.scenario.journals.items()}
        self.assertTrue(all(len(v)==10 for v in previous.values()))
        self.scenario.mark_until('2026-12-01')
        second=self.scenario.bundle(1)
        next_plans=second[-1]['plans']
        exited=sum(len(held-{r['symbol'] for r in next_plans[k.rsplit('-',1)[0]]}) for k,held in previous.items())
        self.assertGreater(exited,0)
        result=self.execute(second);self.assertEqual(result['cases'],8)
        for journal in self.scenario.journals.values():
            state,_,_=journal.replay()
            self.assertEqual(state['rebalances'],2);self.assertEqual(state['halt'],None)
            self.assertGreater(float(state['costs']),0)

    def test_missing_target_price_rejects_all_before_writes(self):
        bad=deepcopy(self.bundle);target=bad[0]['rank_seal']
        plan=json.loads(admission.checked_file(self.scenario.root,target))
        s=plan['plans']['matched_residual'][0]['symbol'];bad[1]['closes'].pop(s)
        before=self.scenario.heads()
        with self.assertRaisesRegex(ValueError,'INVALID_HELD_OR_TARGET_EXECUTION_PRICE'): self.execute(bad)
        self.assertEqual(before,self.scenario.heads());self.assertFalse((self.scenario.root/'transitions').exists())

    def test_missing_held_name_which_is_not_a_new_target_rejects(self):
        self.execute();self.scenario.mark_until('2026-12-01');second=self.scenario.bundle(1)
        for key,j in self.scenario.journals.items():
            held=set(j.replay()[0]['units']);targets={r['symbol'] for r in second[-1]['plans'][key.rsplit('-',1)[0]]}
            if held-targets:
                second[1]['closes'].pop(sorted(held-targets)[0]);break
        else:self.fail('fixture must exercise a held exit')
        before=self.scenario.heads()
        with self.assertRaisesRegex(ValueError,'INVALID_HELD_OR_TARGET_EXECUTION_PRICE'):self.execute(second)
        self.assertEqual(before,self.scenario.heads())

    def test_modified_plan_cannot_reach_ledger(self):
        bad=deepcopy(self.bundle);manifest=bad[0]
        plan=json.loads(admission.checked_file(self.scenario.root,manifest['rank_seal']))
        plan['plans']['matched_residual'].pop()
        manifest['rank_seal']=artifact(self.scenario.root,'tampered-rank.json',plan)
        bad[1]['admitted_manifest_sha256']=sha256(canonical(manifest)).hexdigest();before=self.scenario.heads()
        with self.assertRaisesRegex(ValueError,'RANK_RECOMPUTATION_MISMATCH'):self.execute(bad)
        self.assertEqual(before,self.scenario.heads())

    def test_duplicate_stale_head_and_execution_action_uncertainty_block(self):
        self.execute();after=self.scenario.heads()
        with self.assertRaisesRegex(ValueError,'LEDGER_HEAD_OR_HALT'):self.execute()
        self.assertEqual(after,self.scenario.heads())
        bad=deepcopy(self.bundle);bad[1]['corporate_action_status']='UNRESOLVED_RIGHTS'
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_EXECUTION_ACTIONS'):self.execute(bad)
        self.assertEqual(after,self.scenario.heads())

    def test_identity_evidence_is_not_mocked_and_missing_review_blocks(self):
        bad=deepcopy(self.bundle);bad[0]['identity_reviews'].pop()
        bad[1]['admitted_manifest_sha256']=sha256(canonical(bad[0])).hexdigest();before=self.scenario.heads()
        with self.assertRaisesRegex(ValueError,'IDENTITY_COVERAGE'):self.execute(bad)
        self.assertEqual(before,self.scenario.heads())

    def test_partial_write_is_visible_and_never_auto_completed(self):
        original=ledger.Journal.append;counter=[0]
        def interrupted(journal,request):
            counter[0]+=1
            if counter[0]==2:raise OSError('simulated interruption')
            return original(journal,request)
        with patch.object(ledger.Journal,'append',interrupted):
            with self.assertRaises(OSError):self.execute()
        directories=list((self.scenario.root/'transitions').iterdir());self.assertEqual(len(directories),1)
        receipt=json.loads((directories[0]/'partial.json').read_bytes())
        self.assertEqual(len(receipt['confirmed_case_keys']),1);self.assertFalse(receipt['automatic_retry'])
        self.assertFalse((directories[0]/'complete.json').exists())
        with self.assertRaisesRegex(ValueError,'LEDGER_HEAD_OR_HALT'):self.execute()

    def test_live_packets_and_early_execution_time_are_rejected(self):
        bad=deepcopy(self.bundle);bad[0]['fixture_mode']='LIVE'
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_ONLY'):self.execute(bad)
        bad=deepcopy(self.bundle);bad[1]['received_at']='2026-11-03T20:59:00+00:00'
        with self.assertRaisesRegex(ValueError,'EXECUTION_SESSION_OR_TIME'):self.execute(bad)


if __name__=='__main__':unittest.main()
