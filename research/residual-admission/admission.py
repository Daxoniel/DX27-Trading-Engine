"""Verify immutable evidence and recompute ranks before shadow-input admission only."""
from datetime import date
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import zipfile
import io

from snapshots import canonical, read_ref, utc

ROOT=Path(__file__).resolve().parents[2]
COHORT_HASH='eeadc8c0b4860640fd0a548301f9fb676cef7591168e04d10e98a479d6923d60'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def month_shift(month,offset):
    year,m=map(int,month.split('-'));n=year*12+m-1+offset
    return f'{n//12:04d}-{n%12+1:02d}'


def factors(blob,formation):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        files=archive.namelist()
        if len(files)!=1 or archive.getinfo(files[0]).file_size>2_000_000:
            raise ValueError('FACTOR_ARCHIVE')
        text=archive.read(files[0]).decode('utf-8-sig')
    rows={}; header=False
    for line in text.splitlines():
        row=[x.strip() for x in line.split(',')]
        if row==['','Mkt-RF','SMB','HML','RF']: header=True;continue
        if not header or len(row[0])!=6 or not row[0].isdigit(): continue
        month=row[0][:4]+'-'+row[0][4:];date.fromisoformat(month+'-01')
        if len(row)!=5 or month in rows: raise ValueError('FACTOR_DUPLICATE_OR_SCHEMA')
        values=[float(x) for x in row[1:]]
        if any(not math.isfinite(x) or x in (-99.99,-999) for x in values):
            raise ValueError('FACTOR_VALUE')
        rows[month]=[x/100 for x in values]
    required=[month_shift(formation[:7],offset) for offset in range(-36,0)]
    if not set(required)<=set(rows): raise ValueError('FACTOR_MONTHS_MISSING')
    return {m:rows[m] for m in required}


def pages_complete(refs,bodies,allowed,kind):
    """Each batch starts tokenless and must end explicitly with JSON null."""
    collected={}; covered=set(); current=None; token=None; previous_dates={}; seen_tokens=set()
    for ref,body in zip(refs,bodies):
        params=ref['request']['params'];symbols=tuple(params['symbols'].split(','))
        key=canonical({k:v for k,v in params.items() if k!='page_token'})
        if current is None:
            if 'page_token' in params or covered.intersection(symbols): raise ValueError('BATCH_SCOPE')
            current=key;previous_dates={s:None for s in symbols};seen_tokens=set()
        elif current!=key or params.get('page_token')!=token:
            raise ValueError('PAGE_CHAIN')
        if kind=='bars':
            rows=body.get('bars')
            if rows is None: rows={}
            if not isinstance(rows,dict) or not set(rows)<=set(symbols): raise ValueError('BAR_RESPONSE_SYMBOL')
            for symbol,values in rows.items():
                if not isinstance(values,list): raise ValueError('BAR_SCHEMA')
                for row in values:
                    day=utc(row['t']).date().isoformat()
                    if not params['start']<=day<=params['end'] or (previous_dates[symbol] is not None and day<=previous_dates[symbol]):
                        raise ValueError('BAR_DATE_OR_DUPLICATE')
                    close=row['c'];volume=row['v']
                    if (isinstance(close,bool) or not isinstance(close,(int,float)) or not math.isfinite(close) or close<=0
                        or isinstance(volume,bool) or not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<0):
                        raise ValueError('BAR_VALUE')
                    collected.setdefault(symbol,{})[day]=(close,volume);previous_dates[symbol]=day
        else:
            groups=body.get('corporate_actions')
            if not isinstance(groups,dict): raise ValueError('ACTION_SCHEMA')
            for event_type,rows in groups.items():
                if not isinstance(rows,list): raise ValueError('ACTION_SCHEMA')
                for event in rows:
                    # Unknown/renamed securities require documentary review, not filtering.
                    if not isinstance(event,dict): raise ValueError('ACTION_SCHEMA')
                    if any(event.get(k)=='SOXL' for k in ('symbol','old_symbol','new_symbol')):
                        raise ValueError('RESERVED_SYMBOL')
                    collected.setdefault(event_type,[]).append(event)
        if 'next_page_token' not in body: raise ValueError('PAGE_TERMINATOR_MISSING')
        next_token=body['next_page_token']
        if next_token is not None and (not isinstance(next_token,str) or not next_token or next_token in seen_tokens):
            raise ValueError('PAGE_TOKEN')
        if next_token is not None: seen_tokens.add(next_token)
        token=next_token
        if token is None:
            covered.update(symbols);current=None
    if current is not None or token is not None: raise ValueError('INCOMPLETE_PAGINATION')
    if not covered or not covered<=allowed: raise ValueError('QUERY_COVERAGE')
    return collected,covered


def checked_file(root,ref):
    root=Path(root).resolve();path=(root/ref['path']).resolve()
    if path.parent!=root: raise ValueError('EVIDENCE_PATH')
    blob=path.read_bytes()
    if sha256(blob).hexdigest()!=ref['sha256']: raise ValueError('EVIDENCE_HASH')
    return blob


def identity_check(root,review_refs,assets,required,action_hashes,formation_close,deadline,now):
    reviews={}
    for ref in review_refs:
        row=json.loads(checked_file(root,ref));symbol=row['symbol']
        if symbol in reviews or symbol=='SOXL': raise ValueError('DUPLICATE_REVIEW')
        reviewed=utc(row['reviewed_at'])
        if not formation_close<=reviewed<deadline or reviewed>now: raise ValueError('REVIEW_TIME')
        # Both continuity and action review need retained documentary sources.
        if (row.get('status')!='VERIFIED_ECONOMIC_CONTINUITY_AND_ACTIONS' or not row.get('reviewer')
            or row.get('cohort_sha256')!=COHORT_HASH or set(row.get('action_response_hashes',[]))!=set(action_hashes)
            or not row.get('continuity_reason') or not row.get('action_accounting_reason')):
            raise ValueError('IDENTITY_REVIEW_INCOMPLETE')
        sources=row.get('sources',[])
        if not sources: raise ValueError('IDENTITY_DOCUMENTS_MISSING')
        for source in sources:
            if not source.get('url','').startswith('https://'): raise ValueError('IDENTITY_SOURCE_URL')
            checked_file(root,source)
        asset=assets.get(symbol)
        if not asset or (asset.get('symbol')!=symbol or asset.get('id')!=row.get('asset_id')
                         or asset.get('class')!='us_equity' or asset.get('status')!='active' or asset.get('tradable') is not True):
            raise ValueError('ASSET_IDENTITY_OR_STATUS')
        reviews[symbol]=row
    if not required<=set(reviews): raise ValueError('IDENTITY_COVERAGE')
    return len(required)


def verified_holdings(root,ledgers,now,registered):
    import exchange_calendars as xc
    ledger=load('ra_ledger','research/residual-shadow/ledger.py')
    auditor=load('ra_ledger_audit','research/residual-shadow/ledger_audit.py')
    expected={f'{name}-{bps}bp' for name in ('parent_ordinary','matched_ordinary','matched_relative','matched_residual') for bps in (5,25)}
    if set(ledgers)!=expected: raise ValueError('ALL_LEDGER_HEADS_REQUIRED')
    protocol=json.loads((ROOT/'docs/research/residual-shadow/protocol.json').read_bytes())
    end=protocol['prospective_evaluation_registration']['terminal_mark']
    sessions=[s.date().isoformat() for s in xc.get_calendar('XNYS').sessions_in_range(registered[0]['formation'],end)]
    rebalance=[row['execution'] for row in registered]; held=set();root=Path(root).resolve()
    for key,ref in ledgers.items():
        path=(root/ref['path']).resolve()
        if not path.is_relative_to(root) or path==root: raise ValueError('LEDGER_PATH')
        state,tail,_=ledger.Journal(path).replay(); result=auditor.audit(path)
        if tail!=ref['head_sha256'] or result['halted'] or state['halt']:
            raise ValueError('LEDGER_HEAD_OR_HALT')
        if (state['sessions']!=sessions or state['rebalance_days']!=rebalance or state['initial']!='100000'
            or state['bps']!=(25 if key.endswith('25bp') else 5)):
            raise ValueError('LEDGER_REGISTRATION')
        if state['cursor'] and utc(xc.get_calendar('XNYS').session_close(sessions[state['cursor']-1]).isoformat())>now:
            raise ValueError('LEDGER_FUTURE_MARK')
        held.update(state['units'])
    return held


def admit(root,manifest,observed_at):
    """No broker, network, ledger mutation or automatic promotion, including on success."""
    now=utc(observed_at);window=manifest['window'];formation=window['formation']
    registered=json.loads((ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles']
    if window not in registered: raise ValueError('UNREGISTERED_WINDOW')
    closed=utc(window['formation_close']);deadline=utc(window['execution_open'])
    base=dict(execution_enabled=False,orders=0,automatic_promotion=False,prior_full_exposure_screen='FAIL_RETAINED')
    if now<closed: return dict(base,status='BLOCKED',blockers=['FORMATION_NOT_CLOSED'])
    if now>=deadline: return dict(base,status='SKIP_CYCLE_INCOMPLETE',blockers=['DEADLINE_MISSED'])
    cohort_blob=checked_file(root,manifest['cohort'])
    if sha256(cohort_blob).hexdigest()!=COHORT_HASH: raise ValueError('COHORT_SEAL')
    cohort=json.loads(cohort_blob);allowed={r['symbol'] for r in cohort}|{'SPY'}
    bodies=[];refs=manifest['receipts']
    if not refs: raise ValueError('NO_RECEIPTS')
    for ref in refs:
        blob=read_ref(root,ref,allowed,now)
        if not closed<=utc(ref['request_started_at'])<=utc(ref['received_at'])<deadline:
            raise ValueError('INPUT_NOT_IN_FORMATION_WINDOW')
        bodies.append(blob)
    factor_blobs=[b for ref,b in zip(refs,bodies) if ref['request']['kind']=='factors']
    if len(factor_blobs)!=1: raise ValueError('FACTOR_RECEIPT_COUNT')
    factor_values=factors(factor_blobs[0],formation)
    import exchange_calendars as xc
    if xc.__version__!='4.13.2': raise ValueError('CALENDAR_VERSION')
    start=month_shift(formation[:7],-37)+'-01'
    calendar=[s.date().isoformat() for s in xc.get_calendar('XNYS').sessions_in_range(start,formation)]
    adjusted={};raw={}
    for adjustment in ('all','raw'):
        chosen=[(ref,json.loads(b)) for ref,b in zip(refs,bodies)
                if ref['request']['kind']=='bars' and ref['request']['params']['adjustment']==adjustment]
        if not chosen: raise ValueError('FULL_PRICE_SNAPSHOT_MISSING')
        for ref,_ in chosen:
            params=ref['request']['params']
            if params['start']!=start or params['end']!=formation: raise ValueError('PRICE_WINDOW')
        data,coverage=pages_complete([r for r,b in chosen],[b for r,b in chosen],allowed,'bars')
        if coverage!=allowed: raise ValueError('FULL_UNIVERSE_QUERY_MISSING')
        for symbol,rows in data.items():
            if not set(rows)<=set(calendar): raise ValueError('NONSESSION_PRICE')
        if sorted(data.get('SPY',{}))!=calendar: raise ValueError('BENCHMARK_CALENDAR')
        if adjustment=='all': adjusted={s:{d:v[0] for d,v in rows.items()} for s,rows in data.items()}
        else: raw=data
    rank_module=load('ra_ranking','research/residual-shadow/ranking.py')
    rules=json.loads((ROOT/'docs/research/sector-momentum/protocol.json').read_bytes())
    residual_rules=json.loads((ROOT/'docs/research/residual-momentum/protocol.json').read_bytes())
    result=rank_module.build(formation,adjusted,raw,cohort,calendar,factor_values,rules,residual_rules)
    seal=json.loads(checked_file(root,manifest['rank_seal']))
    if seal['plans']!=result['plans'] or seal['formation']!=formation:
        raise ValueError('RANK_RECOMPUTATION_MISMATCH')
    seal_time=utc(seal['sealed_at'])
    if not closed<=seal_time<deadline or seal_time>now or seal_time<max(utc(r['received_at']) for r in refs):
        raise ValueError('RANK_SEAL_TIME')
    expected_input_hash=sha256(canonical(refs)).hexdigest()
    if seal['snapshot_receipts_sha256']!=expected_input_hash: raise ValueError('RANK_INPUT_BINDING')
    actions=[(r,json.loads(b)) for r,b in zip(refs,bodies) if r['request']['kind']=='actions']
    if not actions: raise ValueError('ACTION_SNAPSHOT_MISSING')
    for ref,_ in actions:
        params=ref['request']['params']
        if params['start']!='2025-04-25' or params['end']!=utc(ref['received_at']).date().isoformat() or params['end']!=now.date().isoformat():
            raise ValueError('ACTION_REVIEW_WINDOW')
    _,action_coverage=pages_complete([r for r,b in actions],[b for r,b in actions],allowed,'actions')
    formation_rows=rank_module.parent.features(formation,adjusted,raw,cohort,calendar,rules)
    held=verified_holdings(root,manifest['ledgers'],now,registered)
    if not held<=allowed-{'SPY'}: raise ValueError('HELD_IDENTITY_SCOPE')
    required={r['symbol'] for r in formation_rows['base']}|held|{r['symbol'] for rows in result['plans'].values() for r in rows}
    if not required<=action_coverage: raise ValueError('ACTION_COVERAGE')
    assets={}
    for ref,b in zip(refs,bodies):
        if ref['request']['kind']=='asset':
            symbol=ref['request']['params']['symbol']
            if symbol in assets: raise ValueError('DUPLICATE_ASSET')
            assets[symbol]=json.loads(b)
    count=identity_check(root,manifest['identity_reviews'],assets,required,
        [r['response_sha256'] for r,b in actions],closed,deadline,now)
    return dict(base,status='SHADOW_INPUTS_ADMISSIBLE',blockers=[],formation=formation,
                audited_scores=result['independently_checked_scores'],identity_reviews=count,
                snapshot_receipts_sha256=expected_input_hash,broker_execution_validated=False,
                source_authenticity_attested=False,clock_assumption='Trusted local capture/review clock; no external time attestation')
