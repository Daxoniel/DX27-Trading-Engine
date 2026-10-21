"""Synthetic-only cross-account transition rehearsal. Cannot activate live/Paper trading."""
from datetime import datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/residual-admission'))
import admission
from snapshots import canonical,utc


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


ledger=load('ri_ledger','research/residual-shadow/ledger.py')
auditor=load('ri_auditor','research/residual-shadow/ledger_audit.py')


def apply(root,manifest,packet,admitted_at,observed_at):
    """Only explicit synthetic fixture roots; callers cannot supply their own targets."""
    root=Path(root).resolve()
    if manifest.get('fixture_mode')!='SYNTHETIC_RI1' or packet.get('kind')!='SYNTHETIC_ADJUSTED_CLOSE':
        raise ValueError('SYNTHETIC_ONLY_NO_LIVE_EXECUTION')
    if packet.get('corporate_action_status')!='SYNTHETIC_REVIEWED_NO_UNMODELED_EVENTS':
        raise ValueError('UNRESOLVED_EXECUTION_ACTIONS')
    window=manifest['window'];now=utc(observed_at);received=utc(packet['received_at'])
    if packet['date']!=window['execution'] or not utc(window['execution_close'])<=received<=now:
        raise ValueError('EXECUTION_SESSION_OR_TIME')
    if utc(admitted_at)>=utc(window['execution_open']) or utc(admitted_at)>received:
        raise ValueError('ADMISSION_TIME')
    decision=admission.admit(root,manifest,admitted_at)
    if decision['status']!='SHADOW_INPUTS_ADMISSIBLE': raise ValueError('INPUTS_NOT_ADMITTED')
    plan=json.loads(admission.checked_file(root,manifest['rank_seal']))
    plan_hash=manifest['rank_seal']['sha256'];manifest_hash=sha256(canonical(manifest)).hexdigest()
    if packet['admitted_manifest_sha256']!=manifest_hash:
        raise ValueError('ADMITTED_MANIFEST_BINDING')
    packet_hash=sha256(canonical(packet)).hexdigest();prepared={}
    for key,ref in sorted(manifest['ledgers'].items()):
        journal=ledger.Journal(root/ref['path']);state,head,_=journal.replay()
        if head!=ref['head_sha256']: raise ValueError('STALE_LEDGER_HEAD')
        if state['cursor']>=len(state['sessions']) or state['sessions'][state['cursor']]!=packet['date']:
            raise ValueError('LEDGER_NOT_AT_EXECUTION_SESSION')
        selector=key.rsplit('-',1)[0]
        request=dict(date=packet['date'],closes=packet['closes'],source_sha256=packet_hash,
                     targets=plan['plans'][selector],rank_plan_sha256=plan_hash)
        predicted,mark=ledger.advance(state,request)
        if predicted['halt'] or mark['nav'] is None: raise ValueError('INVALID_HELD_OR_TARGET_EXECUTION_PRICE')
        prepared[key]=dict(path=ref['path'],before=head,request=request,state=predicted,mark=mark)
    # No writes before every case validates. The multi-file commit is intentionally
    # not described as atomic; explicit receipts expose any interrupted commit.
    operation=sha256(canonical(dict(manifest=manifest_hash,packet=packet_hash))).hexdigest()
    parent=root/'transitions';parent.mkdir(exist_ok=True);out=parent/operation;out.mkdir(exist_ok=False)
    (out/'prepared.json').write_bytes(canonical(dict(manifest_sha256=manifest_hash,packet_sha256=packet_hash,
                                                    case_keys=sorted(prepared)))+b'\n')
    committed=[]
    try:
        for key,row in prepared.items():
            journal=ledger.Journal(root/row['path'])
            if journal.replay()[1]!=row['before']: raise ValueError('CONCURRENT_LEDGER_CHANGE')
            event=journal.append(row['request'])
            state,head,_=journal.replay()
            if state!=row['state'] or event['mark']!=row['mark']: raise ValueError('PREDICTED_STATE_MISMATCH')
            check=auditor.audit(root/row['path'])
            receipt=dict(previous=row['before'],head_sha256=head,audit=check)
            (out/f'{key}.json').write_bytes(canonical(receipt)+b'\n');committed.append(key)
        result=dict(status='SYNTHETIC_TRANSITION_COMPLETE',cases=len(committed),
                    operation_sha256=operation,admitted_manifest_sha256=manifest_hash,execution_packet_sha256=packet_hash,
                    journals_independently_audited=True,orders=0,prospective_observations=0)
        (out/'complete.json').write_bytes(canonical(result)+b'\n')
        return result
    except Exception:
        (out/'partial.json').write_bytes(canonical(dict(status='PARTIAL_OR_FAILED_TRANSITION',
                                                      confirmed_case_keys=committed,automatic_retry=False))+b'\n')
        raise
