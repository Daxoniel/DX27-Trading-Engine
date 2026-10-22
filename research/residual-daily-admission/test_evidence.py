from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import evidence as e
from capture import collect
from pending import prepare
from alias_fixture import AliasScenario,DECISION,artifact

NOW=e.legacy.utc('2026-11-03T21:25:00+00:00')
REVIEW='2026-11-03T21:26:00+00:00'
DECIDE='2026-11-03T21:27:00+00:00'

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.f=AliasScenario(self.root/'SYNTHETIC');self.s=self.f.scenario
        self.patch=patch.object(e.gate,'COHORT_HASH',self.s.cohort_hash);self.patch.start();self.addCleanup(self.patch.stop)
        self.record=e.formation_seal(self.f.capture,self.f.reviews,self.f.aliases,DECISION)
        self.h=e.digest(self.record);self.out=self.root/'daily'
    def bundle(self):return dict(root=str(self.s.root),heads={k:dict(path=k,head_sha256=j.replay()[1]) for k,j in self.s.journals.items()})
    def capture(self,day='2026-11-03',now=NOW):
        helpers=e.gate.admission.load('de_capture_helpers','research/residual-capture/test_capture.py')
        self.transport=None
        def factory(root,allowed):
            obj=helpers.FakeSource(root,allowed,self.s,b'',lambda:now);self.transport=obj;return obj
        result=collect(self.out,self.record,self.h,self.bundle(),day,lambda:now,factory)
        self.assertEqual(result['status'],'CAPTURED_PENDING_DAILY_REVIEW');self.m=json.loads((self.out/'manifest.json').read_bytes())
    def reviews(self,time=REVIEW):
        h=e.sha256((self.out/'manifest.json').read_bytes()).hexdigest()
        src=artifact(self.out,'SYNTHETIC-DOC.txt',b'SYNTHETIC daily review; not an issuer filing');src['url']='https://example.invalid/SYNTHETIC-DE1'
        rows=[]
        for b in self.m['metadata_bindings']:
            row=dict(canonical=b['canonical'],metadata_lookup=b['metadata_lookup'],asset_id=b['asset_id'],
                capture_manifest_sha256=h,cohort_sha256=self.s.cohort_hash,
                action_response_hashes=[r['response_sha256'] for r in self.m['source_refs'] if r['request']['kind']=='actions'],
                reviewed_at=time,reviewer='SYNTHETIC-DE1',status='VERIFIED_ECONOMIC_CONTINUITY_AND_ACTIONS',instrument_type='COMMON_STOCK',
                continuity_reason='SYNTHETIC continuity',action_accounting_reason='SYNTHETIC no unmodeled actions',unmodeled_actions=False,sources=[src])
            rows.append(artifact(self.out,b['canonical']+'.review.json',row))
        return dict(capture_manifest_sha256=h,identity_reviews=rows)
    def assess(self,reviews=None,time=DECIDE):return e.assess(self.out,self.record,self.h,reviews or self.reviews(),time)
    def rewrite_ref(self,index,body=None,params=None):
        ref=self.m['source_refs'][index]
        if params:
            # Restore native RC1 RFC3339 URL generation.
            from source import request_spec
            ref['request']=request_spec(ref['request']['kind'],params,set(self.s.allowed)|{'VSXY'},NOW.date())
            ref['request_sha256']=e.digest(ref['request'])
        if body is not None:
            blob=e.canonical(body);(self.out/'sources'/ref['path']).write_bytes(blob);ref['bytes']=len(blob);ref['response_sha256']=e.sha256(blob).hexdigest()
        (self.out/'manifest.json').write_bytes(e.canonical(self.m)+b'\n')
    def test_native_preopen_to_daily_is_read_only_and_alias_preserved(self):
        before=self.bundle();self.capture();result=self.assess()
        self.assertEqual(result['status'],'DAILY_EVIDENCE_ADMISSIBLE_READ_ONLY');self.assertEqual(before,self.bundle())
        self.assertEqual(len(result['requests']),8);self.assertFalse(result['execution_enabled'])
        self.assertTrue(all('targets' in r for r in result['requests'].values()))
        for ref in self.m['source_refs']:
            if ref['request']['kind'] in ('bars','actions'):self.assertNotIn('VSXY',ref['request']['params']['symbols'].split(','))
    def test_seal_evidence_and_known_hash_tampering(self):
        with self.assertRaisesRegex(ValueError,'FORMATION_SEAL_HASH'):e.validate_seal(self.record,'a'*64)
        (self.f.capture/'SYNTHETIC-NOT-A-FILING.txt').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'FORMATION_EVIDENCE_CHANGED'):e.validate_seal(self.record,self.h)
    def test_pending_and_missing_review(self):
        self.capture();out=prepare(self.out,self.root/'pending');self.assertEqual(out['approved_reviews'],0)
        r=self.reviews();r['identity_reviews']=[]
        with self.assertRaisesRegex(ValueError,'COVERAGE'):self.assess(r)
    def test_stale_heads_and_outside_time(self):
        self.capture();first=next(iter(self.s.journals.values()));first.append(dict(date='2026-11-03',closes={},targets=[],rank_plan_sha256='a'*64,source_sha256='a'*64))
        with self.assertRaisesRegex(ValueError,'HEAD_OR_HALT'):self.assess()
        for time in ('2026-11-03T20:59:00+00:00','2026-11-04T14:30:00+00:00'):
            with self.assertRaisesRegex(ValueError,'DAILY_CLOSE_WINDOW'):e.bounds('2026-11-03',e.legacy.utc(time))
    def test_action_event_and_incomplete_pagination(self):
        self.capture();i=next(i for i,r in enumerate(self.m['source_refs']) if r['request']['kind']=='actions')
        self.rewrite_ref(i,dict(corporate_actions={'forward_splits':[dict(symbol='VSCO',process_date='2026-11-03')]},next_page_token=None))
        with self.assertRaisesRegex(ValueError,'CORPORATE_ACTION'):self.assess()
        self.rewrite_ref(i,dict(corporate_actions={},next_page_token='UNFINISHED'))
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_PAGINATION'):self.assess()
    def test_changed_asset_uuid(self):
        self.capture();i=next(i for i,r in enumerate(self.m['source_refs']) if r['request']['kind']=='asset')
        body=json.loads((self.out/'sources'/self.m['source_refs'][i]['path']).read_bytes());body['id']='CHANGED-SYNTHETIC-UUID'
        self.rewrite_ref(i,body)
        with self.assertRaises(ValueError):self.assess()
    def test_price_coverage_future_and_query_tamper(self):
        self.capture();i=next(i for i,r in enumerate(self.m['source_refs']) if r['request']['kind']=='bars')
        original=json.loads((self.out/'sources'/self.m['source_refs'][i]['path']).read_bytes())
        body=deepcopy(original);body['bars'].pop(next(iter(body['bars'])))
        self.rewrite_ref(i,body)
        with self.assertRaisesRegex(ValueError,'PRICE_COVERAGE'):self.assess()
        body=deepcopy(original);name=next(iter(body['bars']));body['bars'][name].append(dict(t='2026-11-04T05:00:00Z',c=10,v=1))
        self.rewrite_ref(i,body)
        with self.assertRaises(ValueError):self.assess()
        self.rewrite_ref(i,original);self.m['source_refs'][i]['request']['url']+='&BAD=1'
        (self.out/'manifest.json').write_bytes(e.canonical(self.m))
        with self.assertRaisesRegex(ValueError,'SOURCE_REQUEST_SEAL'):self.assess()
    def test_early_preflight_never_opens_transport_or_evidence(self):
        def forbidden(*a):self.fail('source opened')
        result=collect(self.root/'early',None,None,None,'2026-11-03',lambda:e.legacy.utc('2026-10-22T12:00:00+00:00'),forbidden)
        self.assertEqual(result['status'],'BLOCKED_FORMATION_NOT_CLOSED');self.assertFalse((self.root/'early').exists())
        result=e.assess(self.root/'MISSING',None,None,None,'2026-10-22T12:00:00+00:00')
        self.assertEqual(result['status'],'BLOCKED_FORMATION_NOT_CLOSED')
    def test_delayed_source_buffer_is_enforced_on_receipts(self):
        self.capture()
        for ref in self.m['source_refs']:
            ref['request_started_at']='2026-11-03T21:05:00+00:00'
        (self.out/'manifest.json').write_bytes(e.canonical(self.m))
        with self.assertRaisesRegex(ValueError,'DAILY_SOURCE_TIME'):self.assess()
        with self.assertRaisesRegex(ValueError,'DAILY_CLOSE_WINDOW'):
            e.bounds('2026-11-03',e.legacy.utc('2026-11-03T21:19:59+00:00'))
    def test_old_cycle_cannot_authorize_next_rebalance(self):
        with self.assertRaisesRegex(ValueError,'STALE_FORMATION_CYCLE'):
            e.context(self.record,self.h,self.bundle(),'2026-12-02',e.legacy.utc('2026-12-02T21:25:00+00:00'))
    def test_alias_never_becomes_price_symbol(self):
        self.capture();i=next(i for i,r in enumerate(self.m['source_refs']) if r['request']['kind']=='bars')
        p=dict(self.m['source_refs'][i]['request']['params']);names=p['symbols'].split(',');names[0]='VSXY';p['symbols']=','.join(names)
        self.rewrite_ref(i,params=p)
        with self.assertRaisesRegex(ValueError,'CANONICAL_QUERY_ONLY'):self.assess()
    def test_capture_failure_stays_pending_without_journal_changes(self):
        before=self.bundle()
        def failing(root,allowed):raise OSError('SYNTHETIC provider failure')
        out=collect(self.out,self.record,self.h,self.bundle(),'2026-11-03',lambda:NOW,failing)
        self.assertEqual(out['status'],'BLOCKED_DAILY_CAPTURE');self.assertEqual(before,self.bundle())
        self.assertFalse((self.out/'manifest.json').exists())
    def test_held_day_full_spell_restatement_blocks(self):
        self.capture();result=self.assess()
        for key,request in result['requests'].items():self.s.journals[key].append(request)
        # Mark a second holding day using already exposed synthetic prices, then
        # fresh capture on day three must check the entry price, not only yesterday.
        for j in self.s.journals.values():
            state=j.replay()[0];j.append(dict(date='2026-11-04',closes={s:self.s.prices[s]['2026-11-04'] for s in state['units']},source_sha256='b'*64))
        self.out=self.root/'held-day';now=e.legacy.utc('2026-11-05T21:25:00+00:00');self.capture('2026-11-05',now)
        good=self.assess(self.reviews('2026-11-05T21:26:00+00:00'),'2026-11-05T21:27:00+00:00')
        self.assertTrue(all('targets' not in r for r in good['requests'].values()))
        i=next(i for i,r in enumerate(self.m['source_refs']) if r['request']['kind']=='bars' and r['request']['params']['adjustment']=='all')
        body=json.loads((self.out/'sources'/self.m['source_refs'][i]['path']).read_bytes());symbol=next(iter(body['bars']))
        body['bars'][symbol][0]['c']*=.5;self.rewrite_ref(i,body)
        with self.assertRaisesRegex(ValueError,'HELD_PRICE_VINTAGE_CHANGED'):
            self.assess(self.reviews('2026-11-05T21:26:00+00:00'),'2026-11-05T21:27:00+00:00')

if __name__=='__main__':unittest.main()
