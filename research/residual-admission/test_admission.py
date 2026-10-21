from copy import deepcopy
from datetime import date
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import admission
from snapshots import Capture, canonical, read_ref, request_spec, utc

NOW='2026-11-02T12:00:00+00:00'
WINDOW=json.loads((admission.ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles'][0]


def zf(months):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('f.csv',',Mkt-RF,SMB,HML,RF\n'+'\n'.join(m.replace('-','')+',1,2,3,0.1' for m in months))
    return out.getvalue()


def artifact(root,name,body):
    blob=body if isinstance(body,bytes) else canonical(body)
    (root/name).write_bytes(blob)
    return dict(path=name,sha256=sha256(blob).hexdigest())


def snapshot(root,index,kind,params,body,allowed):
    blob=body if isinstance(body,bytes) else canonical(body)
    path=f'{index:04d}.body';(root/path).write_bytes(blob)
    spec=request_spec(kind,params,allowed,date(2026,11,2))
    return dict(path=path,request=spec,request_sha256=sha256(canonical(spec)).hexdigest(),
        response_sha256=sha256(blob).hexdigest(),bytes=len(blob),http_status=200,
        request_started_at='2026-11-02T10:00:00+00:00',received_at='2026-11-02T10:00:01+00:00')


class AdmissionTests(unittest.TestCase):
    def test_endpoint_dates_and_symbol_scope_rejected_before_request(self):
        for kind,params in [('account',{}),('asset',dict(symbol='SOXL')),('asset',dict(symbol='AAA,BBB')),
                            ('factors',dict(url='https://example.com'))]:
            with self.assertRaises(ValueError): request_spec(kind,params,{'AAA','BBB'},date(2026,11,2))
        params=dict(symbols='AAA',start='2025-04-25',end='2026-11-03',data_quality='all',limit=1000)
        with self.assertRaises(ValueError): request_spec('actions',params,{'AAA'},date(2026,11,2))
        params['end']='2026-11-02';params['data_quality']='complete'
        with self.assertRaises(ValueError): request_spec('actions',params,{'AAA'},date(2026,11,2))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'existing';path.mkdir()
            with self.assertRaises(FileExistsError): Capture(path,{'AAA'})

    def test_receipt_hash_path_and_clock_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);ref=snapshot(root,0,'asset',dict(symbol='AAA'),dict(id='x'),{'AAA'})
            self.assertEqual(json.loads(read_ref(root,ref,{'AAA'},utc(NOW))),dict(id='x'))
            for key,value in [('path','../other.body'),('received_at','2026-11-03T12:00:00+00:00'),
                              ('request_started_at','2026-11-02T11:00:00+00:00'),('response_sha256','a'*64)]:
                bad=dict(ref,**{key:value})
                with self.assertRaises((ValueError,FileNotFoundError)): read_ref(root,bad,{'AAA'},utc(NOW))

    def test_incomplete_and_misbound_pagination_never_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);params=dict(symbols='AAA',start='2025-04-25',end='2026-11-02',data_quality='all',limit=1000)
            ref=snapshot(root,0,'actions',params,{}, {'AAA'})
            for body in (dict(corporate_actions={},next_page_token='token'),dict(corporate_actions={})): 
                with self.assertRaises(ValueError): admission.pages_complete([ref],[body],{'AAA'},'actions')
            body=dict(corporate_actions={},next_page_token=None)
            self.assertEqual(admission.pages_complete([ref],[body],{'AAA'},'actions')[1],{'AAA'})
            next_ref=deepcopy(ref);next_ref['request']['params']['page_token']='wrong'
            with self.assertRaises(ValueError): admission.pages_complete([ref,next_ref],
                [dict(corporate_actions={},next_page_token='token'),body],{'AAA'},'actions')

    def test_factor_window_is_dynamic_and_missing_month_blocks(self):
        months=[admission.month_shift('2026-10',i) for i in range(-36,0)]
        self.assertEqual(len(admission.factors(zf(months),'2026-10-30')),36)
        self.assertEqual(admission.factors(zf(months),'2026-10-30')['2026-09'],[.01,.02,.03,.001])
        with self.assertRaisesRegex(ValueError,'FACTOR_MONTHS_MISSING'):
            admission.factors(zf(months[:-1]),'2026-10-30')

    def test_early_and_deadline_checks_do_not_read_inputs_or_enable_execution(self):
        for observed,status in [('2026-10-21T12:00:00+00:00','BLOCKED'),
                                ('2026-11-03T14:30:00+00:00','SKIP_CYCLE_INCOMPLETE')]:
            out=admission.admit('/nonexistent',dict(window=WINDOW),observed)
            self.assertEqual(out['status'],status);self.assertFalse(out['execution_enabled'])
        with self.assertRaises(ValueError): admission.utc('2026-11-02T12:00:00')

    def test_identity_requires_documentary_mapping_not_symbol_or_empty_actions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(ValueError,'IDENTITY_COVERAGE'):
                admission.identity_check(root,[],{'AAA':dict(id='id')},{'AAA'},['f'*64],
                    utc(WINDOW['formation_close']),utc(WINDOW['execution_open']),utc(NOW))
            source=artifact(root,'doc.txt',b'Issuer continuity evidence fixture');source['url']='https://www.sec.gov/fixture'
            review=dict(symbol='AAA',asset_id='id',reviewer='fixture-auditor',status='VERIFIED_ECONOMIC_CONTINUITY_AND_ACTIONS',
                cohort_sha256=admission.COHORT_HASH,reviewed_at='2026-11-02T11:00:00+00:00',
                action_response_hashes=['f'*64],continuity_reason='fixture mapping',action_accounting_reason='fixture reviewed',sources=[source])
            ref=artifact(root,'review.json',review)
            assets={'AAA':dict(id='id',symbol='AAA',status='active',tradable=True,**{'class':'us_equity'})}
            args=(root,[ref],assets,{'AAA'},['f'*64],utc(WINDOW['formation_close']),utc(WINDOW['execution_open']),utc(NOW))
            self.assertEqual(admission.identity_check(*args),1)
            assets['AAA']['id']='different'
            with self.assertRaisesRegex(ValueError,'ASSET_IDENTITY_OR_STATUS'): admission.identity_check(*args)
            (root/'doc.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError,'EVIDENCE_HASH'): admission.identity_check(*args)

    def test_complete_cash_only_bundle_and_mutated_rank_binding(self):
        import exchange_calendars as xc
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);allowed={'AAA','SPY'};cohort=[dict(symbol='AAA',sector='X')]
            c=artifact(root,'cohort.json',cohort);refs=[]
            months=[admission.month_shift('2026-10',i) for i in range(-36,0)]
            refs.append(snapshot(root,0,'factors',{},zf(months),allowed))
            cal=xc.get_calendar('XNYS');days=[s.date().isoformat() for s in cal.sessions_in_range('2023-09-01','2026-10-30')]
            bars={'SPY':[dict(t=day+'T04:00:00Z',c=100+i*.1,v=100) for i,day in enumerate(days)]}
            for adjustment in ('all','raw'):
                params=dict(symbols='AAA,SPY',start='2023-09-01',end='2026-10-30',timeframe='1Day',
                    adjustment=adjustment,asof='2025-04-25',feed='sip',sort='asc',limit=10000)
                refs.append(snapshot(root,len(refs),'bars',params,dict(bars=bars,next_page_token=None),allowed))
            params=dict(symbols='AAA',start='2025-04-25',end='2026-11-02',data_quality='all',limit=1000)
            refs.append(snapshot(root,len(refs),'actions',params,dict(corporate_actions={},next_page_token=None),allowed))
            plans={k:[] for k in ('parent_ordinary','matched_ordinary','matched_relative','matched_residual')}
            seal=dict(plans=plans,formation='2026-10-30',sealed_at='2026-11-02T11:00:00+00:00',
                      snapshot_receipts_sha256=sha256(canonical(refs)).hexdigest())
            sr=artifact(root,'rank.json',seal)
            manifest=dict(window=WINDOW,cohort=c,receipts=refs,rank_seal=sr,identity_reviews=[],ledgers={})
            # Ledger internals are tested independently; this fixture exercises raw data -> rank -> admission.
            with patch.object(admission,'COHORT_HASH',c['sha256']),patch.object(admission,'verified_holdings',return_value=set()):
                out=admission.admit(root,manifest,NOW)
                self.assertEqual(out['status'],'SHADOW_INPUTS_ADMISSIBLE');self.assertFalse(out['execution_enabled'])
                seal['snapshot_receipts_sha256']='0'*64;manifest['rank_seal']=artifact(root,'rank.json',seal)
                with self.assertRaisesRegex(ValueError,'RANK_INPUT_BINDING'): admission.admit(root,manifest,NOW)

    def test_missing_ledgers_or_out_of_tree_ledger_blocks(self):
        with self.assertRaisesRegex(ValueError,'ALL_LEDGER_HEADS_REQUIRED'):
            admission.verified_holdings('.',{},utc(NOW),[WINDOW])


if __name__=='__main__': unittest.main()
