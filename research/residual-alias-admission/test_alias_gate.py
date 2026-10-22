from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import gate
from alias_fixture import AliasScenario,WINDOW
from gate import canonical,legacy


class AliasGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fixture=AliasScenario(Path(self.temp.name)/'SYNTHETIC')

    def test_complete_alias_capture_is_admitted_without_source_or_journal_mutation(self):
        f=self.fixture;heads=f.scenario.heads()
        paths=list((f.capture/'sources').glob('*.body'))
        before={p.name:sha256(p.read_bytes()).hexdigest() for p in paths}
        result=f.assess()
        self.assertEqual(result['status'],'SHADOW_INPUTS_ADMISSIBLE');self.assertEqual(result['metadata_aliases'],1)
        self.assertEqual((result['audited_scores'],result['reviewed_identities']),(55,55))
        self.assertFalse(result['execution_enabled']);self.assertEqual(result['orders'],0)
        self.assertEqual(heads,f.scenario.heads())
        self.assertEqual(before,{p.name:sha256(p.read_bytes()).hexdigest() for p in paths})
        self.assertNotIn('VSXY',{r['symbol'] for r in f.scenario.cohort})

    def test_fresh_review_and_common_stock_classification_are_required(self):
        self.fixture.change_review('VSCO',reviewed_at='2026-11-03T12:00:00+00:00')
        with self.assertRaisesRegex(ValueError,'FRESH_REVIEW_TIME'):self.fixture.assess()
        self.fixture.change_review('VSCO',reviewed_at='2026-11-03T13:05:00+00:00',instrument_type='ETF')
        with self.assertRaisesRegex(ValueError,'IDENTITY_REVIEW_INCOMPLETE'):self.fixture.assess()

    def test_pending_checklist_cannot_approve_alias(self):
        from checklist import prepare
        f=self.fixture;out=prepare(f.capture,f.root/'pending')
        self.assertEqual((out['status'],out['approved_reviews']),('PENDING_NOT_APPROVED',0))
        pending=json.loads((f.root/'pending'/'VSCO.pending.json').read_bytes())
        self.assertEqual(pending['status'],'PENDING_NOT_APPROVED')
        f.change_review('VSCO',status=pending['status'])
        with self.assertRaisesRegex(ValueError,'IDENTITY_REVIEW_INCOMPLETE'):f.assess()
        f.reviews['identity_reviews']=[r for r in f.reviews['identity_reviews'] if r['path']!='VSCO.review.json']
        with self.assertRaisesRegex(ValueError,'IDENTITY_REVIEW_COVERAGE'):f.assess()

    def test_uuid_change_and_alias_table_rewrite_block(self):
        f=self.fixture;f.aliases['VSCO']['asset_id']='different'
        with self.assertRaisesRegex(ValueError,'REGISTERED_ALIAS_BINDING'):f.assess()
        f.manifest['aliases']=deepcopy(f.aliases);f.reseal_manifest()
        with self.assertRaisesRegex(ValueError,'ALIAS_UUID_CHANGED'):f.assess()

    def test_rfc3339_request_tampering_is_detected_even_after_manifest_reseal(self):
        f=self.fixture
        ref=next(r for r in f.manifest['source_refs'] if r['request']['kind']=='bars')
        ref['request']['api_params']['end']=WINDOW['formation']+'T00:00:00Z'
        ref['request_sha256']=sha256(canonical(ref['request'])).hexdigest();f.reseal_manifest()
        with self.assertRaisesRegex(ValueError,'SOURCE_REQUEST_SEAL'):f.assess()

    def test_registered_metadata_alias_cannot_be_used_as_price_symbol(self):
        from source import request_spec
        f=self.fixture
        ref=next(r for r in f.manifest['source_refs'] if r['request']['kind']=='bars' and 'VSCO' in r['request']['params']['symbols'].split(','))
        params=dict(ref['request']['params']);params['symbols']=','.join('VSXY' if s=='VSCO' else s for s in params['symbols'].split(','))
        ref['request']=request_spec('bars',params,f.scenario.allowed|{'VSXY'},legacy.utc('2026-11-03T13:10:00+00:00').date())
        ref['request_sha256']=sha256(canonical(ref['request'])).hexdigest();f.reseal_manifest()
        with self.assertRaisesRegex(ValueError,'NONCANONICAL_PRICE_OR_ACTION_QUERY'):f.assess()

    def test_missing_action_review_document_or_rank_binding_blocks(self):
        f=self.fixture;f.change_review('VSCO',action_response_hashes=[])
        with self.assertRaisesRegex(ValueError,'ACTION_REVIEW_BINDING'):f.assess()
        f.change_review('VSCO',action_response_hashes=[r['response_sha256'] for r in f.manifest['action_refs']])
        (f.capture/'SYNTHETIC-NOT-A-FILING.txt').write_text('altered')
        with self.assertRaisesRegex(ValueError,'EVIDENCE_HASH'):f.assess()

    def test_rank_and_external_head_changes_block(self):
        f=self.fixture;path=f.capture/'candidate-rank-seal.json';plan=json.loads(path.read_bytes())
        saved=path.read_bytes();plan['plans']['matched_residual'].pop();path.write_bytes(canonical(plan))
        with self.assertRaisesRegex(ValueError,'RANK_RECOMPUTATION_MISMATCH'):f.assess()
        path.write_bytes(saved);journal=f.scenario.journals['matched_residual-5bp']
        journal.append(dict(date='2026-11-03',closes={},targets=[],source_sha256='a'*64,rank_plan_sha256='b'*64))
        with self.assertRaisesRegex(ValueError,'LEDGER_HEAD_OR_HALT'):f.assess()


class TimeGateTests(unittest.TestCase):
    def test_actual_clock_boundaries_do_not_require_capture_or_registry_files(self):
        for at,status in [('2026-10-22T12:00:00+00:00','BLOCKED_FORMATION_NOT_CLOSED'),
                          (WINDOW['execution_open'],'SKIP_CYCLE_INCOMPLETE')]:
            result=gate.assess(None,WINDOW,{}, {},at)
            self.assertEqual(result['status'],status);self.assertFalse(result['execution_enabled'])


if __name__=='__main__':unittest.main()
