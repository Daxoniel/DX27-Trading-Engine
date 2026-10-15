"""Fake receipts and constructed prices only; no registration is published here."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.intraday.data import IntradayDataset
from dx27.adapters.intraday.paired_comparison import runtime
from dx27.core.models.market_context import MarketContext
from dx27.research import evaluation
from dx27.research.registration import (CONTRACT, DESIGN_PATH, DESIGN_SHA256, digest,
    load_registration, source_catalogue, stage_calendar, validate_dataset)

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def envelope(tmp_path):
    design=json.loads((ROOT/DESIGN_PATH).read_text(encoding="utf-8"))
    base=datetime.fromisoformat(design['created_at'])+timedelta(seconds=30)
    audit=tmp_path/'audit.json'
    audit.write_text(json.dumps(dict(generated_at=base.isoformat(),stage_exposure={
        'A':'NO_ADDITIONAL_EXPOSURE_RECORDED','B':'NO_ADDITIONAL_EXPOSURE_RECORDED'})))
    reg=dict(contract=CONTRACT,status='REGISTERED_OFFLINE_RESEARCH',evaluation_registered=True,
             execution_enabled=False,stage='A',design_sha256=DESIGN_SHA256,
             source_files=source_catalogue(ROOT),runtime=runtime(),
             calendar_versions={k:stage_calendar(design,k)[0].calendar_version for k in ('A','B')},
             registered_at=(base+timedelta(seconds=30)).isoformat(),
             exposure_recheck=dict(result='NO_ADDITIONAL_EXPOSURE_RECORDED',
                                  checked_at=(base+timedelta(seconds=15)).isoformat(),
                                  audit_sha256=digest(audit.read_bytes())))
    path=tmp_path/'registration.json'
    def write():
        path.write_text(json.dumps(reg));sha=digest(path.read_bytes())
        receipt=dict(registration_sha256=sha,public_commit='a'*40,
                     published_at=(base+timedelta(seconds=60)).isoformat())
        return sha,receipt
    return reg,path,audit,write,base


def load(envelope,**kwargs):
    reg,path,audit,write,base=envelope;sha,receipt=write()
    return load_registration(path,sha,receipt,stage=reg['stage'],exposure_audit_path=audit,**kwargs)


def test_registration_consistency_without_enabling_any_execution(envelope):
    reg,design,gate=load(envelope)
    assert reg['execution_enabled'] is False
    assert design['evaluation_registered'] is False  # immutable design is not an activation
    assert gate['publication_gate'].tzinfo is not None


@pytest.mark.parametrize('kind',['contract','stage','design','runtime','source','enabled','unregistered','future','audit_hash','audit_old','exposure','calendar'])
def test_bad_registration_is_rejected(envelope,kind):
    reg,path,audit,write,base=envelope
    if kind=='calendar':reg['calendar_versions']={}
    if kind=='contract':reg['contract']='other'
    if kind=='stage':reg['stage']='C'
    if kind=='design':reg['design_sha256']='0'*64
    if kind=='runtime':reg['runtime']={}
    if kind=='source':reg['source_files']={}
    if kind=='enabled':reg['execution_enabled']=True
    if kind=='unregistered':reg['evaluation_registered']=False
    if kind=='future':reg['registered_at']='2099-01-01T00:00:00Z'
    if kind=='audit_hash':reg['exposure_recheck']['audit_sha256']='0'*64
    if kind=='audit_old':reg['exposure_recheck']['checked_at']='2000-01-01T00:00:00Z'
    if kind=='exposure':reg['exposure_recheck']['result']='ALREADY_INSPECTED'
    with pytest.raises(ValueError):load(envelope)


def test_published_hash_and_duplicate_json_keys_rejected(envelope):
    reg,path,audit,write,base=envelope;sha,receipt=write()
    receipt['registration_sha256']='0'*64
    with pytest.raises(ValueError):load_registration(path,sha,receipt,stage='A',exposure_audit_path=audit)
    path.write_text('{"contract":"x","contract":"y"}')
    with pytest.raises(ValueError,match='DUPLICATE'):
        load_registration(path,digest(path.read_bytes()),receipt,stage='A',exposure_audit_path=audit)


def test_reserved_stage_requires_public_complete_A_with_same_sources_not_positive_profit(envelope,tmp_path):
    reg,path,audit,write,base=envelope;reg['stage']='B'
    with pytest.raises(ValueError,match='A_REPORT_REQUIRED'):load(envelope)
    a=dict(status='COMPLETE_REGISTERED_HISTORICAL_ANALYSIS',stage='A',design_sha256=DESIGN_SHA256,
           execution_enabled=False,evaluation_registered=True,analysis_completed_at=(base+timedelta(seconds=80)).isoformat(),
           integrity_complete=True,source_files=reg['source_files'],runtime=reg['runtime'],primary_R1_net_return=-.99)
    ap=tmp_path/'a.json';ap.write_text(json.dumps(a));sha,receipt=write()
    receipt['stage_A_report']=dict(sha256=digest(ap.read_bytes()),public_commit='b'*40,
                                 published_at=(base+timedelta(seconds=90)).isoformat())
    _,_,gate=load_registration(path,sha,receipt,stage='B',exposure_audit_path=audit,a_report_path=ap)
    assert gate['publication_gate']==datetime.fromisoformat(receipt['stage_A_report']['published_at'])
    a['integrity_complete']=False;ap.write_text(json.dumps(a));receipt['stage_A_report']['sha256']=digest(ap.read_bytes())
    with pytest.raises(ValueError,match='INCOMPLETE'):
        load_registration(path,sha,receipt,stage='B',exposure_audit_path=audit,a_report_path=ap)


def test_no_quote_file_is_opened_if_registration_missing_or_invalid(monkeypatch,tmp_path):
    called=[]
    monkeypatch.setattr(evaluation,'load_csv',lambda _:called.append(True))
    p=tmp_path/'not-registered.json';p.write_text('{}')
    with pytest.raises(ValueError):
        evaluation.run_registered(p,digest(p.read_bytes()),{},'do-not-open.csv',stage='A',exposure_audit_path=p)
    assert not called


@pytest.fixture
def constructed():
    sessions=load_xnys_calendar(date(2025,3,10),date(2025,3,12)).sessions
    n=sum(int((s.closes_at-s.opens_at).total_seconds()/60) for s in sessions)
    design={'data':{'source':'ALPACA_HISTORICAL_SIP','feed':'sip','adjustment':'raw','bar_label':'interval_start','symbols':['IWM','QQQ','SPY']},
       'stages':{'A':{'warmup':{'start_session_inclusive':'2025-03-10'},
         'evaluation':{'start_session_inclusive':'2025-03-10','end_session_exclusive':'2025-03-13','expected_sessions':3},
         'expected_context_sessions':3,'expected_context_regular_minutes':n,
         'request_start':'2025-03-10T00:00:00Z','request_end_exclusive':'2025-03-13T00:00:00Z'}}}
    bars=tuple(MarketContext(symbol,s.opens_at+i*timedelta(minutes=1),'1m',100.,101.,99.,100.,1000.)
        for s in sessions for i in range(int((s.closes_at-s.opens_at).total_seconds()/60)) for symbol in ['IWM','QQQ','SPY'])
    meta=dict(design['data'],start=design['stages']['A']['request_start'],end_exclusive=design['stages']['A']['request_end_exclusive'],
              csv_sha256='a'*64,raw_sha256='b'*64,rows=len(bars),retrieved_started_at='2026-10-15T00:01:00Z',retrieved_completed_at='2026-10-15T00:02:00Z')
    gate={'publication_gate':datetime(2026,10,15,tzinfo=timezone.utc)}
    return IntradayDataset(bars,meta),design,gate


def test_full_regular_calendar_accepts_only_all_symbols_and_minutes(constructed):
    ds,design,gate=constructed
    _,sessions,evaluation_sessions=validate_dataset(ds,design,'A',gate,now=datetime(2026,10,16,tzinfo=timezone.utc))
    assert len(sessions)==len(evaluation_sessions)==3


@pytest.mark.parametrize('kind',['missing','duplicate','zero','symbol','feed','bounds','hash','before','future','rows','ohlc'])
def test_source_and_calendar_guards_fail_closed(constructed,kind):
    ds,design,gate=constructed;b=list(ds.bars);meta=dict(ds.provenance)
    if kind=='missing':b.pop();meta['rows']=len(b)
    if kind=='duplicate':b[-1]=b[0]
    if kind=='zero':b[0]=replace(b[0],volume=0.)
    if kind=='symbol':b[0]=replace(b[0],symbol='TQQQ')
    if kind=='feed':meta['feed']='iex'
    if kind=='bounds':meta['start']='2025-03-09T00:00:00Z'
    if kind=='hash':meta.pop('raw_sha256')
    if kind=='before':meta['retrieved_started_at']='2026-10-14T23:00:00Z'
    if kind=='future':meta['retrieved_completed_at']='2099-01-01T00:00:00Z'
    if kind=='rows':meta['rows']+=1
    if kind=='ohlc':b[0]=replace(b[0],close=float('nan'))
    with pytest.raises(ValueError):
        validate_dataset(IntradayDataset(tuple(b),meta),design,'A',gate,now=datetime(2026,10,16,tzinfo=timezone.utc))


def test_declared_real_design_calendar_counts_without_market_data():
    d=json.loads((ROOT/DESIGN_PATH).read_text(encoding="utf-8"))
    assert len(stage_calendar(d,'A')[2])==251
    assert len(stage_calendar(d,'B')[2])==64


def test_guarded_runner_composition_and_archive_tamper(envelope,constructed,tmp_path,monkeypatch):
    # Small constructed schedule replaces the year only inside this test seam.
    # The real API always loads the immutable canonical design.
    import csv
    from dx27.adapters.intraday.data import CSV_FIELDS
    ds,tiny_design,_=constructed
    reg,path,audit,write,base=envelope;sha,receipt=write()
    canonical_loader=evaluation.load_registration
    def small_registration(*args,**kwargs):
        r,d,g=canonical_loader(*args,**kwargs)
        tiny=deepcopy(tiny_design)
        tiny['baseline_config_template']=d['baseline_config_template']
        return r,tiny,g
    monkeypatch.setattr(evaluation,'load_registration',small_registration)
    source=tmp_path/'constructed.csv'
    with source.open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(CSV_FIELDS)
        for b in ds.bars:
            writer.writerow([b.symbol,b.timestamp.isoformat(),b.open,b.high,b.low,b.close,b.volume])
    archive=source.with_suffix('.csv.raw.jsonl');archive.write_text('{}\n')
    meta=dict(ds.provenance,csv_sha256=digest(source.read_bytes()),raw_sha256=digest(archive.read_bytes()),
              retrieved_started_at=(base+timedelta(seconds=90)).isoformat(),
              retrieved_completed_at=(base+timedelta(seconds=120)).isoformat())
    source.with_suffix('.csv.metadata.json').write_text(json.dumps(meta))
    report,results=evaluation.run_registered(path,sha,receipt,source,stage='A',exposure_audit_path=audit)
    assert report['status']=='COMPLETE_REGISTERED_HISTORICAL_ANALYSIS'
    assert report['integrity_complete'] and not report['execution_enabled']
    assert report['effectiveness']=='NOT_ESTABLISHED'
    assert len(results['R1'].daily)==3
    assert all(r.summary['performance_admissible'] for r in results.values())
    archive.write_text('{"tampered":true}\n')
    with pytest.raises(ValueError,match='archive'):
        evaluation.run_registered(path,sha,receipt,source,stage='A',exposure_audit_path=audit)


def test_guard_requires_actual_exposure_audit_bytes(envelope):
    reg,path,audit,write,base=envelope;sha,receipt=write()
    with pytest.raises(ValueError,match='AUDIT_FILE_REQUIRED'):
        load_registration(path,sha,receipt,stage='A')
    audit.write_text('{}')
    with pytest.raises(ValueError,match='AUDIT_SEAL'):
        load_registration(path,sha,receipt,stage='A',exposure_audit_path=audit)
