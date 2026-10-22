"""DC1 local proxy-journal commit. No network, brokerage or order interface."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/residual-daily-admission'))
import evidence as e
from cli import verify_code as verify_parent

LOCK='.dc1-writer.lock'
OPERATIONS='dc1-operations'
require=e.require


def verify_code():
    verify_parent();public=ROOT/'docs/research/residual-daily-commit'
    seal=json.loads((public/'code-seal.json').read_bytes())
    require(sha256((public/'protocol.md').read_bytes()).hexdigest()==seal['protocol_sha256'],'DC_PROTOCOL_SEAL')
    for name,h in seal['files'].items():
        require(sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==h,'DC_CODE_SEAL')


def write_receipt(path,data):
    event=dict(data=data,sha256=e.digest(data))
    with Path(path).open('xb') as stream:
        stream.write(e.canonical(event)+b'\n');stream.flush();os.fsync(stream.fileno())
    return event['sha256']


def read_receipt(path):
    path=Path(path);require(not path.is_symlink(),'RECEIPT_SYMLINK')
    event=json.loads(path.read_bytes())
    require(set(event)=={'data','sha256'} and e.digest(event['data'])==event['sha256'],'RECEIPT_HASH')
    return event['data'],event['sha256']


def acquire(root,now):
    lock=root/LOCK
    try:lock.mkdir()
    except FileExistsError:raise ValueError('WRITER_LOCK_PRESENT_MANUAL_REVIEW') from None
    token=uuid4().hex
    # If ownership writing fails, leave the exclusive lock for investigation.
    write_receipt(lock/'owner.json',dict(token=token,created_at=now.isoformat(),pid=os.getpid()))
    return token


def owned(root,token):
    lock=root/LOCK;require(not lock.is_symlink(),'LOCK_CHANGED')
    owner,_=read_receipt(lock/'owner.json')
    require(owner['token']==token,'LOCK_OWNERSHIP_CHANGED')


def release(root,token):
    owned(root,token);lock=root/LOCK
    require({p.name for p in lock.iterdir()}=={'owner.json'},'LOCK_CONTENTS_CHANGED')
    (lock/'owner.json').unlink();lock.rmdir()


def prior_operations(root,paths):
    parent=root/OPERATIONS
    require(not parent.is_symlink(),'OPERATIONS_SYMLINK')
    if not parent.exists():return
    require(parent.is_dir(),'OPERATIONS_NOT_DIRECTORY')
    ancestors={}
    for key,path in paths.items():
        journal=e.ledger.Journal(root/path);journal.replay()
        ancestors[key]={json.loads(p.read_bytes())['sha256'] for p in journal.root.iterdir()}
    for out in parent.iterdir():
        require(out.is_dir() and not out.is_symlink(),'UNKNOWN_OPERATION_ENTRY')
        require((out/'complete.json').is_file() and not (out/'partial.json').exists(),'INCOMPLETE_OPERATION_NO_RETRY')
        prepared,ph=read_receipt(out/'prepared.json');complete,_=read_receipt(out/'complete.json')
        require(out.name==ph==complete['operation_sha256'],'OPERATION_HASH')
        require(set(prepared['cases'])==set(paths)==set(complete['case_receipts']),'OPERATION_CASE_COVERAGE')
        require(complete['status']=='LOCAL_PROXY_MARK_COMPLETE' and complete['journal_writes']==8,'OPERATION_NOT_COMPLETE')
        require({p.name for p in out.iterdir()}=={'prepared.json','complete.json'}|{k+'.json' for k in paths},'OPERATION_FILES_CHANGED')
        require(e.inventory(prepared['capture'])==prepared['evidence_files'],'PAST_DAILY_EVIDENCE_CHANGED')
        for key,path in paths.items():
            row=prepared['cases'][key];case,ch=read_receipt(out/(key+'.json'))
            require(row['path']==path and case['path']==path,'OPERATION_ACCOUNT_BINDING')
            require(ch==complete['case_receipts'][key] and case['before']==row['before'],'CASE_RECEIPT_BINDING')
            require(case['request_sha256']==e.digest(row['request'])
                    and case['state_sha256']==e.digest(row['state'])
                    and case['mark_sha256']==e.digest(row['mark']),'CASE_PREDICTION_BINDING')
            require(case['audit']['status']=='PASS' and not case['audit']['halted'],'CASE_AUDIT')
            require(case['after'] in ancestors[key],'COMPLETED_HEAD_NOT_ANCESTOR')


def commit(capture,record,seal_hash,reviews,proposal,proposal_hash,clock=lambda:datetime.now(timezone.utc)):
    verify_code();started=clock()
    if started<e.legacy.utc(e.gate.collector.windows()[0]['formation_close']):
        return dict(status='BLOCKED_FORMATION_NOT_CLOSED',observed_at=started.isoformat(),
                    network_requests=0,lock_created=False,journal_writes=0,orders=0)
    # Freeze caller objects; hashes refer to canonical full JSON, excluding file newline.
    record=json.loads(e.canonical(record));reviews=json.loads(e.canonical(reviews));proposal=json.loads(e.canonical(proposal))
    require(e.digest(proposal)==proposal_hash,'PROPOSAL_FILE_HASH')
    manifest,_=e.validate_seal(record,seal_hash)
    root=Path(manifest['ledgers']['root']).resolve();require(root.is_dir(),'ACCOUNT_ROOT_MISSING')
    paths={k:r['path'] for k,r in manifest['ledgers']['heads'].items()}
    capture=Path(capture).resolve()
    require(not capture.is_relative_to(root),'EVIDENCE_INSIDE_ACCOUNT_ROOT')
    token=acquire(root,started);operation_started=False;success=False
    out=None;confirmed=[];attempted=[];last_time=started
    try:
        prior_operations(root,paths)
        before=e.inventory(capture)
        fresh=e.assess(capture,record,seal_hash,reviews,clock().isoformat())
        require(fresh==proposal and fresh['status']=='DAILY_EVIDENCE_ADMISSIBLE_READ_ONLY','PROPOSAL_REVALIDATION_MISMATCH')
        daily=json.loads((capture/'manifest.json').read_bytes());day=fresh['date']
        def checkpoint():
            nonlocal last_time
            now=clock();require(now>=last_time,'CLOCK_MOVED_BACKWARDS');last_time=now
            require(e.bounds(day,now)[0]=='IN_WINDOW','COMMIT_DEADLINE')
            owned(root,token)
            require(e.inventory(capture)==before,'DAILY_EVIDENCE_CHANGED_DURING_COMMIT')
            return now
        checkpoint();prepared={}
        for key,ref in sorted(daily['ledgers']['heads'].items()):
            require(ref['path']==paths[key],'ACCOUNT_PATH_BINDING')
            journal=e.ledger.Journal(root/ref['path']);state,head,count=journal.replay()
            require(head==ref['head_sha256'],'STALE_LEDGER_HEAD')
            audit=e.auditor.audit(journal.root)
            require(audit['status']=='PASS' and not audit['halted'],'PRECOMMIT_AUDIT_FAILED')
            predicted,mark=e.ledger.advance(state,fresh['requests'][key])
            require(not predicted['halt'],'PRECOMMIT_PREDICTED_HALT')
            prepared[key]=dict(path=ref['path'],before=head,request=fresh['requests'][key],
                               state=predicted,mark=mark,event_index=count)
        require(set(prepared)==set(paths) and len(prepared)==8,'EIGHT_CASES_REQUIRED')
        checkpoint()
        for key,row in prepared.items():
            require(e.ledger.Journal(root/row['path']).replay()[1]==row['before'],'PREWRITE_HEAD_CHANGED')
        data=dict(version='DC1',capture=str(capture),evidence_files=before,cases=prepared,
                  formation_seal_sha256=seal_hash,proposal_file_sha256=proposal_hash,
                  proposal_requests_sha256=fresh['proposal_sha256'],started_at=started.isoformat(),
                  code_seal_sha256=sha256((ROOT/'docs/research/residual-daily-commit/code-seal.json').read_bytes()).hexdigest())
        operation=e.digest(data);parent=root/OPERATIONS;parent.mkdir(exist_ok=True)
        require(not parent.is_symlink(),'OPERATIONS_SYMLINK')
        out=parent/operation;out.mkdir(exist_ok=False);operation_started=True
        write_receipt(out/'prepared.json',data);case_hashes={}
        for key,row in prepared.items():
            checkpoint();journal=e.ledger.Journal(root/row['path'])
            require(journal.replay()[1]==row['before'],'CONCURRENT_JOURNAL_CHANGE')
            attempted.append(key)
            event=journal.append(row['request'])
            with (journal.root/f"{row['event_index']:06d}.json").open('r+b') as stream:os.fsync(stream.fileno())
            state,head,_=journal.replay()
            require(state==row['state'] and event['mark']==row['mark'] and head==event['sha256'],'COMMIT_REPLAY_MISMATCH')
            audit=e.auditor.audit(journal.root)
            require(audit['status']=='PASS' and not audit['halted'],'POSTCOMMIT_AUDIT_FAILED')
            receipt=dict(path=row['path'],before=row['before'],after=head,request_sha256=e.digest(row['request']),
                         state_sha256=e.digest(state),mark_sha256=e.digest(event['mark']),audit=audit)
            case_hashes[key]=write_receipt(out/(key+'.json'),receipt);confirmed.append(key)
        finished=checkpoint()
        for key,row in prepared.items():
            state,_,_=e.ledger.Journal(root/row['path']).replay()
            case,_=read_receipt(out/(key+'.json'))
            require(e.ledger.Journal(root/row['path']).replay()[1]==case['after'] and state==row['state'],'FINAL_HEAD_CHANGED')
        result=dict(status='LOCAL_PROXY_MARK_COMPLETE',operation_sha256=operation,date=day,
                    case_receipts=case_hashes,journal_writes=len(confirmed),finished_at=finished.isoformat(),
                    independently_audited=True,broker_execution_enabled=False,network_requests=0,orders=0,
                    atomic_multi_account_transaction=False,source_authenticity_attested=False)
        write_receipt(out/'complete.json',result);success=True
        return result
    except BaseException:
        if operation_started:
            try:
                write_receipt(out/'partial.json',dict(status='PARTIAL_OR_UNCERTAIN_COMMIT',confirmed_case_keys=confirmed,
                    attempted_case_keys=attempted,unconfirmed_writes_may_exist=True,automatic_retry=False))
            except OSError:pass # The retained lock/incomplete operation still blocks retries.
        raise
    finally:
        if not operation_started or success:release(root,token)
