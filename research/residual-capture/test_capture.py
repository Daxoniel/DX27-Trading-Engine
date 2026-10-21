from copy import deepcopy
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse

import collector
import registry
from source import canonical,legacy,read_ref,request_spec
sys.path.insert(0,str(collector.ROOT/'research/residual-integration'))
from fixture import Scenario

WINDOW=collector.windows()[0]
NOW=legacy.utc('2026-11-03T13:00:00+00:00')


class FakeSource:
    """Clearly labelled local fixtures, no network/credentials and real RC1 receipts."""
    def __init__(self,root,allowed,scenario,factor_blob,clock):
        self.root=Path(root);self.root.mkdir();self.allowed=allowed;self.refs=[]
        self.scenario=scenario;self.factors=factor_blob;self.clock=clock
        self.requested=[];self.bad_asset=False;self.expire_after_get=None

    def get(self,kind,params):
        self.requested.append((kind,dict(params)));now=self.clock()
        spec=request_spec(kind,params,self.allowed,now.date())
        if kind=='factors':blob=self.factors
        elif kind=='asset':
            symbol=params['symbol'];blob=canonical(dict(symbol='WRONG' if self.bad_asset else symbol,
                id='SYNTHETIC-ASSET-'+symbol,status='active',tradable=True,**{'class':'us_equity'}))
        elif kind=='actions':blob=canonical(dict(corporate_actions={},next_page_token=None))
        else:
            names=params['symbols'].split(',');flat=[]
            for s in names:
                flat.extend((s,dict(t=d+'T05:00:00Z',c=p,v=10_000_000)) for d,p in sorted(self.scenario.prices[s].items())
                            if params['start']<=d<=params['end'])
            offset=int(params.get('page_token','0'));rows=flat[offset:offset+params['limit']];bars={}
            for s,row in rows:bars.setdefault(s,[]).append(row)
            token=str(offset+len(rows)) if offset+len(rows)<len(flat) else None
            blob=canonical(dict(bars=bars,next_page_token=token))
        filename=f'{len(self.refs):05d}.body';(self.root/filename).write_bytes(blob)
        ref=dict(path=filename,request=spec,request_sha256=sha256(canonical(spec)).hexdigest(),
            response_sha256=sha256(blob).hexdigest(),bytes=len(blob),http_status=200,
            source_format='RC1',request_started_at=now.isoformat(),received_at=now.isoformat(),fixture_origin='SYNTHETIC_NOT_HTTP')
        self.refs.append(ref)
        if self.expire_after_get:self.expire_after_get()
        return blob,ref


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_early_late_and_unknown_window_make_no_requests(self):
        for now,status in [(legacy.utc('2026-10-21T12:00:00+00:00'),'BLOCKED_FORMATION_NOT_CLOSED'),
                           (legacy.utc(WINDOW['execution_open']),'SKIP_CYCLE_INCOMPLETE')]:
            def forbidden(*args):self.fail('transport must not be initialized outside window')
            out=collector.collect(self.root/status,WINDOW,b'',{}, {},lambda:now,forbidden)
            self.assertEqual(out['status'],status);self.assertEqual(out['network_requests'],0)
        with self.assertRaisesRegex(ValueError,'UNREGISTERED_WINDOW'):
            collector.collect(self.root/'bad',dict(formation='2026-10-29'),b'',{}, {},lambda:NOW)

    def test_explicit_utc_price_bounds_and_reserved_scope(self):
        p=dict(symbols='AAA',start='2023-09-01',end='2026-10-30',timeframe='1Day',adjustment='all',
            asof='2025-04-25',feed='sip',sort='asc',limit=10000)
        spec=request_spec('bars',p,{'AAA'},NOW.date());query=parse_qs(urlparse(spec['url']).query)
        self.assertEqual(query['end'],['2026-10-30T23:59:59Z']);self.assertEqual(spec['params']['end'],'2026-10-30')
        self.assertEqual(query['start'],['2023-09-01T00:00:00Z'])
        with self.assertRaises(ValueError):request_spec('bars',dict(p,symbols='SOXL'),{'SOXL'},NOW.date())

    def test_empty_account_configuration_is_read_only_and_collectible(self):
        from prepare_accounts import prepare
        root=self.root/'proxy-accounts';out=prepare(root)
        self.assertEqual(out['journal_count'],8);self.assertEqual(out['held_names'],0)
        config=json.loads((root/'ledger-heads.json').read_bytes())
        held=collector.admission.verified_holdings(config['root'],config['heads'],NOW,collector.windows())
        self.assertEqual(held,set())
        with self.assertRaises(FileExistsError):prepare(root)

    def test_alias_has_no_price_rewrite_and_rejects_collision_uuid_or_date(self):
        row=dict(canonical='VSCO',lookup='VSXY',effective_date='2026-06-02',cusip='926400102',asset_id='fixture-id')
        aliases=registry.validate([row],{'VSCO'})
        asset=dict(symbol='VSXY',id='fixture-id',status='active',tradable=True,**{'class':'us_equity'})
        bound=registry.bind('VSCO',asset,aliases,date(2026,10,30))
        self.assertEqual((bound['canonical'],bound['metadata_lookup']),('VSCO','VSXY'))
        self.assertFalse(bound['economic_identity_review_complete'])
        with self.assertRaises(ValueError):registry.validate([row],{'VSCO','VSXY'})
        with self.assertRaises(ValueError):registry.bind('VSCO',dict(asset,id='new'),aliases,NOW.date())
        with self.assertRaises(ValueError):registry.bind('VSCO',asset,aliases,date(2026,6,1))
        with self.assertRaises(ValueError):registry.validate([row,row],{'VSCO'})

    def scenario(self):
        s=Scenario(self.root/'fixture');s.mark_until('2026-11-02');bundle=s.bundle(0)
        first=bundle[0]['receipts'][0];factors=(s.root/first['path']).read_bytes()
        cohort=(s.root/s.cohort_ref['path']).read_bytes()
        ledgers=dict(root=str(s.root),heads=bundle[0]['ledgers'])
        return s,factors,cohort,ledgers

    def test_factor_gap_stops_before_prices_or_ledger_reads(self):
        cohort=canonical([dict(symbol='AAA',sector='X')]);cohort_hash=sha256(cohort).hexdigest();seen=[]
        def factory(root,allowed):
            # Reuse a small legacy factor fixture, explicitly missing the required tail.
            import io,zipfile
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:z.writestr('fixture.csv',',Mkt-RF,SMB,HML,RF\n202608,1,2,3,0.1')
            obj=FakeSource(root,allowed,None,out.getvalue(),lambda:NOW);seen.append(obj);return obj
        with patch.object(collector,'COHORT_HASH',cohort_hash):
            out=collector.collect(self.root/'capture',WINDOW,cohort,{}, {},lambda:NOW,factory)
        self.assertEqual(out['status'],'BLOCKED_FACTOR_MONTHS_MISSING')
        self.assertEqual([r[0] for r in seen[0].requested],['factors'])
        self.assertFalse((self.root/'capture'/'manifest.json').exists())

    def test_complete_nonempty_synthetic_collection_keeps_identity_pending(self):
        s,factors,cohort,ledgers=self.scenario();seen=[];heads_before=s.heads()
        def factory(root,allowed):
            obj=FakeSource(root,allowed,s,factors,lambda:NOW);seen.append(obj);return obj
        with patch.object(collector,'COHORT_HASH',sha256(cohort).hexdigest()):
            out=collector.collect(self.root/'capture',WINDOW,cohort,{},ledgers,lambda:NOW,factory)
        self.assertEqual(out['status'],'CAPTURED_PENDING_IDENTITY_REVIEW')
        self.assertEqual(heads_before,s.heads())
        self.assertEqual(out['eligible_scores_audited'],55);self.assertEqual(out['metadata_bindings'],55)
        self.assertEqual(out['full_universe_queries'],56);self.assertGreater(out['stock_requests'],4)
        self.assertFalse(out['execution_enabled']);self.assertFalse(out['legacy_RA1_compatible'])
        self.assertTrue(all(set(p['symbols'].split(','))<=s.allowed for kind,p in seen[0].requested if kind=='bars'))
        manifest=json.loads((self.root/'capture'/'manifest.json').read_bytes())
        first=manifest['source_refs'][0]
        body=(self.root/'capture'/'sources'/first['path']).read_bytes()
        self.assertEqual(read_ref(self.root/'capture'/'sources',first,s.allowed,NOW),body)
        (self.root/'capture'/'sources'/first['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SOURCE_RESPONSE_SEAL'):
            read_ref(self.root/'capture'/'sources',first,s.allowed,NOW)

    def test_metadata_failure_leaves_no_final_seal(self):
        s,factors,cohort,ledgers=self.scenario()
        def factory(root,allowed):
            obj=FakeSource(root,allowed,s,factors,lambda:NOW);obj.bad_asset=True;return obj
        with patch.object(collector,'COHORT_HASH',sha256(cohort).hexdigest()):
            out=collector.collect(self.root/'capture',WINDOW,cohort,{},ledgers,lambda:NOW,factory)
        self.assertEqual(out['status'],'BLOCKED_CAPTURE_INCOMPLETE')
        self.assertEqual(out['failure_code'],'ASSET_UNRESOLVED');self.assertEqual(out['new_rankings'],1)
        self.assertFalse((self.root/'capture'/'candidate-rank-seal.json').exists())

    def test_deadline_crossing_stops_after_factor_request(self):
        s,factors,cohort,ledgers=self.scenario();clock=[NOW]
        def factory(root,allowed):
            obj=FakeSource(root,allowed,s,factors,lambda:clock[0])
            obj.expire_after_get=lambda:clock.__setitem__(0,legacy.utc(WINDOW['execution_open']))
            return obj
        with patch.object(collector,'COHORT_HASH',sha256(cohort).hexdigest()):
            out=collector.collect(self.root/'capture',WINDOW,cohort,{},ledgers,lambda:clock[0],factory)
        self.assertEqual(out['status'],'BLOCKED_CAPTURE_INCOMPLETE');self.assertEqual(out['failure_code'],'CAPTURE_DEADLINE')
        self.assertEqual(out['stock_requests'],0);self.assertFalse((self.root/'capture'/'manifest.json').exists())


if __name__=='__main__':unittest.main()
