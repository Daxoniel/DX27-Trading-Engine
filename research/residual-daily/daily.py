"""RD1 synthetic-only guard; never authorizes real source or broker execution."""
import json
from pathlib import Path
import sys
import exchange_calendars as xc
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/residual-integration'))
from transition import ledger, auditor, canonical, sha256, utc


def require(condition, message):
    if not condition: raise ValueError(message)


def apply(root, refs, packet, observed_at):
    require(packet.get('mode')=='SYNTHETIC_RD1', 'SYNTHETIC_ONLY')
    root=Path(root); operations=root/'daily-operations'
    if operations.exists():
        require(all((p/'complete.json').is_file() for p in operations.iterdir()), 'INCOMPLETE_OPERATION_NO_RETRY')
    cal=xc.get_calendar('XNYS'); day=packet['date']
    require(cal.is_session(day), 'NOT_XNYS_SESSION')
    received=utc(packet['received_at']); now=utc(observed_at)
    require(cal.session_close(day).to_pydatetime()<=received<=now, 'SESSION_NOT_CLOSED')
    require(packet.get('action_review')=='SYNTHETIC_NO_UNMODELED_EVENTS','UNRESOLVED_ACTIONS')
    expected={s+'-'+str(b)+'bp' for s in ('parent_ordinary','matched_ordinary','matched_relative','matched_residual') for b in (5,25)}
    require(set(refs)==expected, 'EIGHT_REGISTERED_ACCOUNTS_REQUIRED')
    prepared={}; required=set(); held=set(); h=ledger.digest(packet)
    paths=set()
    for key,ref in sorted(refs.items()):
        path=(root/ref['path']).resolve()
        require(path.is_relative_to(root.resolve()) and path not in paths,'JOURNAL_PATH')
        paths.add(path); journal=ledger.Journal(path); state,head,count=journal.replay()
        require(head==ref['head_sha256'], 'STALE_LEDGER_HEAD')
        require(state['bps']==int(key.rsplit('-',1)[1][:-2]),'COST_BINDING')
        require(state['cursor']<len(state['sessions']) and state['sessions'][state['cursor']]==day,'NEXT_SESSION_REQUIRED')
        held.update(state['units']); required.update(state['units'])
        if state['units']:
            previous=json.loads((path/f'{count-1:06d}.json').read_bytes())['request']
            require(packet.get('anchor_date')==previous['date'],'ANCHOR_DATE')
            require(set(state['units'])<=set(packet.get('anchor_closes',{})), 'MISSING_ANCHOR')
            for symbol in state['units']:
                require(ledger.number(packet.get('anchor_closes',{}).get(symbol),True)==ledger.number(previous['closes'][symbol],True),'ADJUSTMENT_BASIS_CHANGED')
        request=dict(date=day,closes=packet['closes'],source_sha256=h)
        if day in state['rebalance_days']:
            require(packet.get('rank_mode')=='SYNTHETIC_RD1','SYNTHETIC_RANK_REQUIRED')
            targets=packet['plans'][key.rsplit('-',1)[0]]
            required.update(ledger.weights(targets))
            request.update(targets=targets,rank_plan_sha256=ledger.digest(packet['plans']))
        predicted,mark=ledger.advance(state,request)
        require(not predicted['halt'],'INVALID_PRICE_OR_PLAN')
        prepared[key]=(path,head,request,predicted,mark)
    require(set(packet['closes'])==required and 'SOXL' not in packet['closes'],'EXACT_PRICE_COVERAGE')
    require(set(packet.get('anchor_closes',{}))==held,'EXACT_ANCHOR_COVERAGE')
    operations.mkdir(exist_ok=True); out=operations/h; out.mkdir(exist_ok=False)
    (out/'prepared.json').write_bytes(canonical(dict(packet_sha256=h,heads={k:v[1] for k,v in prepared.items()})))
    done=[]
    try:
        for key,(path,head,request,predicted,mark) in prepared.items():
            journal=ledger.Journal(path)
            require(journal.replay()[1]==head,'CONCURRENT_CHANGE')
            event=journal.append(request)
            require(event['state']==predicted and event['mark']==mark,'PREDICTION_MISMATCH')
            audit=auditor.audit(path)
            require(audit['status']=='PASS','AUDIT_FAILED')
            (out/(key+'.json')).write_bytes(canonical(dict(head=event['sha256'],audit=audit)))
            done.append(key)
        result=dict(status='SYNTHETIC_DAILY_COMPLETE',cases=len(done),orders=0,prospective_observations=0,source_authenticity_verified=False)
        (out/'complete.json').write_bytes(canonical(result)); return result
    except Exception:
        (out/'partial.json').write_bytes(canonical(dict(confirmed=done,automatic_retry=False)))
        raise
