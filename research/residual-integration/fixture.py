"""Explicit deterministic synthetic evidence; never provider or issuer observations."""
from contextlib import contextmanager
from datetime import date
from hashlib import sha256
import io
import json
import math
from pathlib import Path
from unittest.mock import patch
import zipfile
import exchange_calendars as xc

from transition import admission,ledger
from snapshots import canonical,request_spec

COUNT=55
SELECTORS=('parent_ordinary','matched_ordinary','matched_relative','matched_residual')


def symbol(i): return 'A'+chr(65+i//26)+chr(65+i%26)


def artifact(root,name,value):
    blob=value if isinstance(value,bytes) else canonical(value)
    (root/name).write_bytes(blob)
    return dict(path=name,sha256=sha256(blob).hexdigest())


def snapshot(root,prefix,refs,kind,params,body,allowed,day):
    blob=body if isinstance(body,bytes) else canonical(body)
    name=f'{prefix}-{len(refs):04d}.body';(root/name).write_bytes(blob)
    spec=request_spec(kind,params,allowed,date.fromisoformat(day))
    ref=dict(path=name,request=spec,request_sha256=sha256(canonical(spec)).hexdigest(),
             response_sha256=sha256(blob).hexdigest(),bytes=len(blob),http_status=200,
             request_started_at=day+'T10:00:00+00:00',received_at=day+'T10:00:01+00:00',
             fixture_origin='SYNTHETIC_RI1_NOT_HTTP_OBSERVATION')
    refs.append(ref)
    return ref


class Scenario:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.registered=json.loads((admission.ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles']
        self.cal=xc.get_calendar('XNYS')
        self.calendar=[x.date().isoformat() for x in self.cal.sessions_in_range('2023-09-01','2026-12-02')]
        self.cohort=[dict(symbol=symbol(i),sector=f'SECTOR-{i//11}') for i in range(COUNT)]
        self.cohort_ref=artifact(self.root,'synthetic-cohort.json',self.cohort)
        self.cohort_hash=self.cohort_ref['sha256'];self.allowed={r['symbol'] for r in self.cohort}|{'SPY'}
        self.prices={s:{} for s in self.allowed};values={s:40+k*.4 for k,s in enumerate(sorted(self.allowed))}
        for i,day in enumerate(self.calendar):
            market=.00015+.003*math.sin(i*.37)+.001*math.cos(i*.11)
            values['SPY']*=1+market;self.prices['SPY'][day]=values['SPY']
            for k,row in enumerate(self.cohort):
                own=.00005+k*.000002+.0008*math.sin(i*(.027+k*.00011)+k*.19)
                if day.startswith('2026-10'):
                    own+=.012*(.5-k/(COUNT-1))
                s=row['symbol'];values[s]*=1+2.2*market+own;self.prices[s][day]=values[s]
        self.journals={}
        sessions=[x.date().isoformat() for x in self.cal.sessions_in_range(self.registered[0]['formation'],'2027-04-30')]
        for selector in SELECTORS:
            for bps in (5,25):
                key=f'{selector}-{bps}bp';journal=ledger.Journal(self.root/key)
                journal.create(ledger.initialize(sessions,[r['execution'] for r in self.registered],bps))
                self.journals[key]=journal
        doc=b'SYNTHETIC_RI1: fabricated common-stock identity and no-unmodeled-action evidence for software tests; not a filing.'
        self.source=artifact(self.root,'SYNTHETIC-IDENTITY.txt',doc)
        self.source['url']='https://example.invalid/SYNTHETIC-RI1-NOT-A-FILING'

    @contextmanager
    def cohort_boundary(self):
        # This is the ONLY substituted validation boundary. All economic/model,
        # source-byte, rank, identity and journal/audit functions remain real.
        with patch.object(admission,'COHORT_HASH',self.cohort_hash):
            yield

    def heads(self): return {k:j.replay()[1] for k,j in self.journals.items()}

    def mark_until(self,last_day):
        for key,j in self.journals.items():
            while True:
                state,_,_=j.replay();day=state['sessions'][state['cursor']]
                if day>last_day: break
                if day in state['rebalance_days']: raise ValueError('CANNOT_BYPASS_REBALANCE')
                j.append(dict(date=day,closes={s:self.prices[s][day] for s in state['units']},source_sha256='a'*64))

    def bundle(self,cycle):
        prefix=f'cycle-{cycle}';window=self.registered[cycle];formation=window['formation'];day=window['execution']
        start=admission.month_shift(formation[:7],-37)+'-01'
        calendar=[d for d in self.calendar if start<=d<=formation]
        factors={}
        for i in range(36):
            m=admission.month_shift(formation[:7],i-36)
            index=int(m[:4])*12+int(m[5:])
            factors[m]=[.023*math.sin(index*.39)+.002,.009*math.cos(index*.53),.011*math.sin(index*.73+1),.001]
        csv=',Mkt-RF,SMB,HML,RF\n'+'\n'.join(m.replace('-','')+','+','.join(str(v*100) for v in row) for m,row in factors.items())
        zipped=io.BytesIO()
        with zipfile.ZipFile(zipped,'w') as z:z.writestr('SYNTHETIC.csv',csv)
        refs=[];snapshot(self.root,prefix,refs,'factors',{},zipped.getvalue(),self.allowed,day)
        symbols=sorted(self.allowed)
        for adjustment in ('all','raw'):
            for offset in range(0,len(symbols),50):
                names=symbols[offset:offset+50]
                body=dict(bars={s:[dict(t=d+'T05:00:00Z',c=self.prices[s][d],v=10_000_000) for d in calendar] for s in names},next_page_token=None)
                params=dict(symbols=','.join(names),start=start,end=formation,timeframe='1Day',adjustment=adjustment,
                            asof='2025-04-25',feed='sip',sort='asc',limit=10000)
                snapshot(self.root,prefix,refs,'bars',params,body,self.allowed,day)
        action_refs=[]
        for offset in range(0,COUNT,50):
            names=[r['symbol'] for r in self.cohort[offset:offset+50]]
            params=dict(symbols=','.join(names),start='2025-04-25',end=day,data_quality='all',limit=1000)
            action_refs.append(snapshot(self.root,prefix,refs,'actions',params,dict(corporate_actions={},next_page_token=None),self.allowed,day))
        reviews=[]
        for row in self.cohort:
            s=row['symbol'];asset_id='SYNTHETIC-ASSET-'+s
            snapshot(self.root,prefix,refs,'asset',dict(symbol=s),dict(symbol=s,id=asset_id,status='active',tradable=True,**{'class':'us_equity'}),self.allowed,day)
            review=dict(symbol=s,asset_id=asset_id,reviewer='SYNTHETIC-RI1-FIXTURE',
                status='VERIFIED_ECONOMIC_CONTINUITY_AND_ACTIONS',cohort_sha256=self.cohort_hash,
                reviewed_at=day+'T12:00:00+00:00',action_response_hashes=[r['response_sha256'] for r in action_refs],
                continuity_reason='SYNTHETIC common-stock continuity fixture; no real issuer claim',
                action_accounting_reason='SYNTHETIC no-unmodeled-events fixture',sources=[self.source])
            reviews.append(artifact(self.root,f'{prefix}-review-{s}.json',review))
        ranking=admission.load('ri_real_ranking','research/residual-shadow/ranking.py')
        adjusted={s:{d:self.prices[s][d] for d in calendar} for s in self.allowed}
        raw={s:{d:(self.prices[s][d],10_000_000) for d in calendar} for s in self.allowed}
        rules=json.loads((admission.ROOT/'docs/research/sector-momentum/protocol.json').read_bytes())
        residual=json.loads((admission.ROOT/'docs/research/residual-momentum/protocol.json').read_bytes())
        calculated=ranking.build(formation,adjusted,raw,self.cohort,calendar,factors,rules,residual)
        if calculated['independently_checked_scores']==0: raise ValueError('FIXTURE_MUST_BE_NONEMPTY')
        plan=dict(formation=formation,plans=calculated['plans'],sealed_at=day+'T12:30:00+00:00',
                  snapshot_receipts_sha256=sha256(canonical(refs)).hexdigest())
        plan_ref=artifact(self.root,f'{prefix}-rank.json',plan)
        manifest=dict(fixture_mode='SYNTHETIC_RI1',window=window,cohort=self.cohort_ref,receipts=refs,
                      rank_seal=plan_ref,identity_reviews=reviews,
                      ledgers={k:dict(path=k,head_sha256=j.replay()[1]) for k,j in self.journals.items()})
        packet=dict(kind='SYNTHETIC_ADJUSTED_CLOSE',date=day,
                    received_at=window['execution_close'],corporate_action_status='SYNTHETIC_REVIEWED_NO_UNMODELED_EVENTS',
                    closes={s:self.prices[s][day] for s in sorted(self.allowed-{'SPY'})},
                    admitted_manifest_sha256=sha256(canonical(manifest)).hexdigest())
        artifact(self.root,f'{prefix}-manifest.json',manifest);artifact(self.root,f'{prefix}-execution.json',packet)
        return manifest,packet,day+'T13:00:00+00:00',window['execution_close'],calculated
