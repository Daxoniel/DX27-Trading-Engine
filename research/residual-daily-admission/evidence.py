"""DE1 read-only formation receipts and daily evidence verification."""
from decimal import Decimal
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
import exchange_calendars as xc
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/residual-alias-admission'))
import gate
from decide import verify_code as verify_parent
from source import Source, read_ref, canonical, legacy
require=gate.require
ledger=gate.admission.load('de_ledger','research/residual-shadow/ledger.py')
auditor=gate.admission.load('de_auditor','research/residual-shadow/ledger_audit.py')


def digest(value):return sha256(canonical(value)).hexdigest()


def inventory(root):
    root=Path(root).resolve();result={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(),'EVIDENCE_SYMLINK')
        if path.is_file():result[str(path.relative_to(root)).replace('\\','/')]=sha256(path.read_bytes()).hexdigest()
    return result


def formation_seal(capture,reviews,aliases,observed_at):
    verify_parent();capture=Path(capture).resolve()
    manifest=json.loads((capture/'manifest.json').read_bytes());window=manifest['window']
    before=inventory(capture)
    decision=gate.assess(capture,window,reviews,aliases,observed_at)
    require(inventory(capture)==before,'FORMATION_CHANGED_DURING_SEAL')
    require(decision['status']=='SHADOW_INPUTS_ADMISSIBLE','FORMATION_NOT_ADMITTED')
    return dict(version='DE1_FORMATION',sealed_at=observed_at,window=window,capture=str(capture),
                capture_files=before,decision=decision,reviews=reviews,aliases=aliases,
                parent_seal_sha256=sha256((ROOT/'docs/research/residual-alias-admission/code-seal.json').read_bytes()).hexdigest(),
                clock_trust='LOCAL_ONLY_NO_EXTERNAL_ATTESTATION',orders=0)


def validate_seal(record,expected_hash):
    require(digest(record)==expected_hash,'FORMATION_SEAL_HASH')
    require(record['version']=='DE1_FORMATION','FORMATION_SEAL_SCHEMA');verify_parent()
    require(record['parent_seal_sha256']==sha256((ROOT/'docs/research/residual-alias-admission/code-seal.json').read_bytes()).hexdigest(),'PARENT_SEAL_BINDING')
    window=record['window'];require(window in gate.collector.windows(),'UNREGISTERED_FORMATION')
    require(gate.collector.window_state(window,legacy.utc(record['sealed_at']))=='IN_WINDOW','PREOPEN_SEAL_TIME')
    capture=Path(record['capture']);require(inventory(capture)==record['capture_files'],'FORMATION_EVIDENCE_CHANGED')
    manifest=json.loads((capture/'manifest.json').read_bytes());plan_blob=(capture/'candidate-rank-seal.json').read_bytes()
    decision=record['decision'];require(decision['status']=='SHADOW_INPUTS_ADMISSIBLE','FORMATION_NOT_ADMITTED')
    require(window==manifest['window'] and manifest['aliases']==record['aliases'],'FORMATION_BINDING')
    require(manifest['cohort_sha256']==gate.COHORT_HASH,'COHORT_SEAL')
    require(decision['capture_manifest_sha256']==sha256((capture/'manifest.json').read_bytes()).hexdigest()
            and decision['rank_seal_sha256']==sha256(plan_blob).hexdigest()
            and decision['review_manifest_sha256']==digest(record['reviews']),'DECISION_BINDING')
    return manifest,json.loads(plan_blob)


def bounds(day,now):
    require(xc.__version__=='4.13.2','CALENDAR_VERSION');cal=xc.get_calendar('XNYS')
    first=gate.collector.windows()[0]
    if now<legacy.utc(first['formation_close']):return 'BLOCKED_FORMATION_NOT_CLOSED',None,None
    require(cal.is_session(day),'NONSESSION_DAY')
    close=cal.session_close(day).to_pydatetime();deadline=cal.session_open(cal.next_session(day)).to_pydatetime()
    require(close+timedelta(minutes=20)<=now<deadline,'DAILY_CLOSE_WINDOW')
    return 'IN_WINDOW',close,deadline


def context(record,expected_hash,bundle,day,now):
    status,close,deadline=bounds(day,now)
    require(status=='IN_WINDOW',status)
    manifest,plan=validate_seal(record,expected_hash);window=record['window']
    cycles=gate.collector.windows();active=[r for r in cycles if r['execution']<=day]
    if active:require(window==active[-1],'STALE_FORMATION_CYCLE')
    else:require(window==cycles[0] and day>=window['formation'],'INITIAL_FORMATION_CYCLE')
    require(legacy.utc(record['sealed_at'])<=now,'FUTURE_FORMATION_SEAL')
    require(str(Path(bundle['root']).resolve())==str(Path(manifest['ledgers']['root']).resolve()),'ACCOUNT_ROOT_BINDING')
    held=gate.admission.verified_holdings(bundle['root'],bundle['heads'],now,cycles)
    require(len({str((Path(bundle['root'])/r['path']).resolve()) for r in bundle['heads'].values()})==8,'DUPLICATE_JOURNAL_PATH')
    required=set(held);history={};cal=xc.get_calendar('XNYS');previous=cal.previous_session(day).date().isoformat()
    if day==window['execution']:required.update(r['symbol'] for rows in plan['plans'].values() for r in rows)
    for key,ref in bundle['heads'].items():
        original=manifest['ledgers']['heads'][key]
        require(ref['path']==original['path'],'ACCOUNT_PATH_BINDING')
        journal=ledger.Journal(Path(bundle['root'])/ref['path']);state,_,count=journal.replay()
        require(state['cursor']<len(state['sessions']) and state['sessions'][state['cursor']]==day,'EXACT_NEXT_SESSION')
        events=[json.loads(p.read_bytes()) for p in sorted(journal.root.iterdir())]
        require(original['head_sha256'] in {e['sha256'] for e in events},'FORMATION_HEAD_NOT_ANCESTOR')
        # Current uninterrupted holding spell only; full replay above certifies event/state arithmetic.
        for symbol in state['units']:
            for event in reversed(events[1:]):
                if symbol not in event['state']['units']:break
                request=event['request'];value=request['closes'][symbol]
                prior=history.setdefault(symbol,{})
                require(request['date'] not in prior or ledger.number(prior[request['date']],True)==ledger.number(value,True),'CROSS_ACCOUNT_PRICE_CONFLICT')
                prior[request['date']]=value
    bindings={r['canonical']:r for r in manifest['metadata_bindings']}
    require(required<=set(bindings),'FORMATION_IDENTITY_COVERAGE')
    start=min([previous]+[d for rows in history.values() for d in rows])
    return dict(required=required,held=held,history=history,start=start,previous=previous,close=close,deadline=deadline,
                plan=plan,bindings=bindings,cohort_sha256=manifest['cohort_sha256'])


def assess(root,record,expected_hash,reviews,observed_at):
    now=legacy.utc(observed_at)
    if now<legacy.utc(gate.collector.windows()[0]['formation_close']):
        return dict(status='BLOCKED_FORMATION_NOT_CLOSED',network_requests=0,journal_writes=0,orders=0,execution_enabled=False)
    root=Path(root);m=json.loads((root/'manifest.json').read_bytes());day=m['date']
    c=context(record,expected_hash,m['ledgers'],day,now)
    require(m['version']=='DE1_DAILY' and m['formation_seal_sha256']==expected_hash and m['cohort_sha256']==c['cohort_sha256'],'DAILY_SEAL_BINDING')
    require(m['start']==c['start'] and m['action_start']==c['previous'],'DAILY_QUERY_WINDOW')
    allowed=c['required'];aliases=record['aliases'];metadata=allowed|{r['lookup'] for r in aliases.values()}
    refs=m['source_refs'];bodies=[];exact_bodies={};paths=set()
    for ref in refs:
        require(ref['path'] not in paths,'DUPLICATE_SOURCE');paths.add(ref['path'])
        require(ref['request']['kind'] in ('bars','actions','asset'),'DAILY_SOURCE_KIND')
        blob=read_ref(root/'sources',ref,metadata,now)
        require(c['close']+timedelta(minutes=20)<=legacy.utc(ref['request_started_at'])<=legacy.utc(ref['received_at'])<c['deadline'],'DAILY_SOURCE_TIME')
        if ref['request']['kind']!='asset':require(set(ref['request']['params']['symbols'].split(','))<=allowed,'CANONICAL_QUERY_ONLY')
        bodies.append(json.loads(blob));exact_bodies[ref['path']]=json.loads(blob,parse_float=Decimal)
    prices={};sessions={d.date().isoformat() for d in xc.get_calendar('XNYS').sessions_in_range(c['start'],day)}
    for adjustment in ('all','raw'):
        chosen=[(r,b) for r,b in zip(refs,bodies) if r['request']['kind']=='bars' and r['request']['params']['adjustment']==adjustment]
        if not allowed:require(not chosen,'UNNEEDED_PRICES');continue
        for r,b in chosen:
            p=r['request']['params'];require(p['start']==c['start'] and p['end']==day,'BAR_WINDOW')
        data,coverage=gate.admission.pages_complete([r for r,b in chosen],[b for r,b in chosen],allowed,'bars')
        require(coverage==allowed and set(data)==allowed,'PRICE_COVERAGE')
        require(all(set(rows)==sessions for rows in data.values()),'PRICE_SESSION_COVERAGE')
        # Validate schema/pagination using the sealed parent, then retain the
        # original decimal token for money/vintage checks rather than binary float.
        for r,b in chosen:
            for symbol,rows in exact_bodies[r['path']].get('bars',{}).items():
                for row in rows:
                    date=legacy.utc(row['t']).date().isoformat()
                    data[symbol][date]=(str(row['c']),data[symbol][date][1])
        prices[adjustment]=data
    actions=[(r,b) for r,b in zip(refs,bodies) if r['request']['kind']=='actions']
    if allowed:
        for r,b in actions:
            p=r['request']['params'];require(p['start']==c['previous'] and p['end']==now.date().isoformat(),'ACTION_WINDOW')
        events,coverage=gate.admission.pages_complete([r for r,b in actions],[b for r,b in actions],allowed,'actions')
        require(coverage==allowed,'ACTION_COVERAGE')
        require(not any(events.values()),'CORPORATE_ACTION_REQUIRES_SEPARATE_ACCOUNTING')
    else:require(not actions,'UNNEEDED_ACTIONS')
    for symbol,rows in c['history'].items():
        for date,old in rows.items():require(ledger.number(prices['all'][symbol][date][0],True)==ledger.number(old,True),'HELD_PRICE_VINTAGE_CHANGED')
    assets={}
    for ref,body in zip(refs,bodies):
        if ref['request']['kind']=='asset':
            lookup=ref['request']['params']['symbol'];require(lookup not in assets,'DUPLICATE_ASSET');assets[lookup]=(ref,body)
    bindings={}
    for symbol in sorted(allowed):
        lookup=aliases.get(symbol,{}).get('lookup',symbol);ref,body=assets[lookup]
        binding=gate.registry.bind(symbol,body,aliases,now.date())
        require(binding['asset_id']==c['bindings'][symbol]['asset_id'],'ASSET_UUID_CHANGED')
        bindings[symbol]=dict(binding,source_path=ref['path'],source_response_sha256=ref['response_sha256'])
    require(set(assets)=={r['metadata_lookup'] for r in bindings.values()},'ASSET_SCOPE')
    require(m['metadata_bindings']==list(bindings.values()),'DAILY_METADATA_BINDING')
    h=sha256((root/'manifest.json').read_bytes()).hexdigest()
    require(reviews['capture_manifest_sha256']==h,'DAILY_REVIEW_MANIFEST')
    latest=max([c['close']]+[legacy.utc(r['received_at']) for r in refs])
    count=gate.review_identity(root,reviews['identity_reviews'],bindings,allowed,[r['response_sha256'] for r,b in actions],h,c['cohort_sha256'],c['close'],c['deadline'],now,latest)
    require(len(reviews['identity_reviews'])==len(allowed),'EXACT_DAILY_REVIEW_SCOPE')
    closes={s:str(prices['all'][s][day][0]) for s in sorted(allowed)}
    requests={}
    for key in m['ledgers']['heads']:
        request=dict(date=day,closes=closes,source_sha256=h)
        if day==record['window']['execution']:request.update(targets=c['plan']['plans'][key.rsplit('-',1)[0]],rank_plan_sha256=record['decision']['rank_seal_sha256'])
        journal=ledger.Journal(Path(m['ledgers']['root'])/m['ledgers']['heads'][key]['path'])
        predicted,mark=ledger.advance(journal.replay()[0],request);require(not predicted['halt'],'PREDICTED_HALT');requests[key]=request
    return dict(status='DAILY_EVIDENCE_ADMISSIBLE_READ_ONLY',date=day,reviewed_identities=count,
                manifest_sha256=h,review_manifest_sha256=digest(reviews),formation_seal_sha256=expected_hash,
                proposal_sha256=digest(requests),requests=requests,execution_enabled=False,journal_writes=0,orders=0,
                source_authenticity_attested=False,automatic_promotion=False)
