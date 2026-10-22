"""Explicit synthetic alias fixture; no issuer/provider evidence claims."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import gate
from gate import collector,canonical,legacy

helpers=gate.admission.load('aa_capture_helpers','research/residual-capture/test_capture.py')
NOW=legacy.utc('2026-11-03T13:00:00+00:00')
DECISION='2026-11-03T13:10:00+00:00'
WINDOW=collector.windows()[0]


def artifact(root,name,value):
    blob=value if isinstance(value,bytes) else canonical(value)
    (Path(root)/name).write_bytes(blob)
    return dict(path=name,sha256=sha256(blob).hexdigest())


class AliasScenario:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.scenario=helpers.Scenario(self.root/'SYNTHETIC-ACCOUNTS')
        s=self.scenario;old=s.cohort[0]['symbol'];s.cohort[0]['symbol']='VSCO'
        s.prices['VSCO']=s.prices.pop(old);s.allowed.remove(old);s.allowed.add('VSCO')
        s.cohort_ref=artifact(s.root,'synthetic-cohort.json',s.cohort);s.cohort_hash=s.cohort_ref['sha256']
        self.cohort_blob=(s.root/s.cohort_ref['path']).read_bytes();s.mark_until('2026-11-02')
        bundle=s.bundle(0);factors=(s.root/bundle[0]['receipts'][0]['path']).read_bytes()
        self.aliases={'VSCO':dict(canonical='VSCO',lookup='VSXY',effective_date='2026-06-02',cusip='926400102',
                                  asset_id='SYNTHETIC-ASSET-VSXY',case_sha256='a'*64)}
        self.capture=self.root/'capture'
        ledgers=dict(root=str(s.root),heads=bundle[0]['ledgers'])
        def transport(root,allowed):return helpers.FakeSource(root,allowed,s,factors,lambda:NOW)
        with patch.object(collector,'COHORT_HASH',s.cohort_hash):
            result=collector.collect(self.capture,WINDOW,self.cohort_blob,self.aliases,ledgers,lambda:NOW,transport)
        if result['status']!='CAPTURED_PENDING_IDENTITY_REVIEW':raise ValueError('FIXTURE_CAPTURE_FAILED')
        self.manifest=json.loads((self.capture/'manifest.json').read_bytes())
        self.reviews=dict(capture_manifest_sha256=sha256((self.capture/'manifest.json').read_bytes()).hexdigest(),identity_reviews=[])
        source=artifact(self.capture,'SYNTHETIC-NOT-A-FILING.txt',b'SYNTHETIC AA1 issuer/continuity/action evidence; no real assertion.')
        source['url']='https://example.invalid/SYNTHETIC-AA1'
        for binding in self.manifest['metadata_bindings']:
            review=dict(canonical=binding['canonical'],metadata_lookup=binding['metadata_lookup'],asset_id=binding['asset_id'],
                capture_manifest_sha256=self.reviews['capture_manifest_sha256'],cohort_sha256=s.cohort_hash,
                action_response_hashes=[r['response_sha256'] for r in self.manifest['action_refs']],
                reviewed_at='2026-11-03T13:05:00+00:00',reviewer='SYNTHETIC-AA1-REVIEWER',
                status='VERIFIED_ECONOMIC_CONTINUITY_AND_ACTIONS',instrument_type='COMMON_STOCK',unmodeled_actions=False,
                continuity_reason='SYNTHETIC continuity including canonical versus metadata alias',
                action_accounting_reason='SYNTHETIC no unresolved events',sources=[source])
            self.reviews['identity_reviews'].append(artifact(self.capture,binding['canonical']+'.review.json',review))

    def assess(self):
        with patch.object(gate,'COHORT_HASH',self.scenario.cohort_hash):
            return gate.assess(self.capture,WINDOW,self.reviews,self.aliases,DECISION)

    def reseal_manifest(self):
        blob=canonical(self.manifest)+b'\n';(self.capture/'manifest.json').write_bytes(blob)
        h=sha256(blob).hexdigest();self.reviews['capture_manifest_sha256']=h
        report=json.loads((self.capture/'report.json').read_bytes());report['manifest_sha256']=h
        (self.capture/'report.json').write_bytes(canonical(report)+b'\n')
        plan=json.loads((self.capture/'candidate-rank-seal.json').read_bytes());plan['capture_manifest_sha256']=h
        (self.capture/'candidate-rank-seal.json').write_bytes(canonical(plan)+b'\n')
        for index,ref in enumerate(self.reviews['identity_reviews']):
            row=json.loads((self.capture/ref['path']).read_bytes());row['capture_manifest_sha256']=h
            self.reviews['identity_reviews'][index]=artifact(self.capture,ref['path'],row)

    def change_review(self,symbol,**changes):
        for index,ref in enumerate(self.reviews['identity_reviews']):
            row=json.loads((self.capture/ref['path']).read_bytes())
            if row['canonical']==symbol:
                row.update(changes);self.reviews['identity_reviews'][index]=artifact(self.capture,ref['path'],row);return
        raise ValueError('FIXTURE_REVIEW_NOT_FOUND')
