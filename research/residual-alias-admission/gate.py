"""Native RC1 proof checks; reads actual aliases without rewriting provider evidence."""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/residual-capture'))
import collector
import registry
from source import canonical,read_ref,legacy
admission=collector.admission
COHORT_HASH=collector.COHORT_HASH


def require(value,code):
    if not value:raise ValueError(code)


def review_identity(root,refs,bindings,required,action_hashes,capture_hash,cohort_hash,closed,deadline,now,latest_input):
    checked={}
    for ref in refs:
        row=json.loads(admission.checked_file(root,ref));symbol=row['canonical']
        require(symbol not in checked and symbol!='SOXL','DUPLICATE_IDENTITY_REVIEW')
        reviewed=legacy.utc(row['reviewed_at'])
        require(closed<=reviewed<deadline and latest_input<=reviewed<=now,'FRESH_REVIEW_TIME')
        binding=bindings.get(symbol)
        require(binding is not None,'REVIEW_WITHOUT_ASSET')
        require(row['metadata_lookup']==binding['metadata_lookup'] and row['asset_id']==binding['asset_id'],'IDENTITY_BINDING')
        require(row.get('capture_manifest_sha256')==capture_hash and row.get('cohort_sha256')==cohort_hash,'REVIEW_INPUT_BINDING')
        require(set(row.get('action_response_hashes',[]))==set(action_hashes),'ACTION_REVIEW_BINDING')
        require(row.get('status')=='VERIFIED_ECONOMIC_CONTINUITY_AND_ACTIONS'
                and row.get('instrument_type')=='COMMON_STOCK' and row.get('reviewer')
                and row.get('continuity_reason') and row.get('action_accounting_reason')
                and row.get('unmodeled_actions') is False,'IDENTITY_REVIEW_INCOMPLETE')
        require(bool(row.get('sources')),'IDENTITY_SOURCES_MISSING')
        for source in row['sources']:
            require(source.get('url','').startswith('https://'),'DOCUMENT_URL')
            admission.checked_file(root,source)
        checked[symbol]=row
    require(required<=set(checked),'IDENTITY_REVIEW_COVERAGE')
    return len(required)


def assess(root,window,reviews,aliases,observed_at):
    now=legacy.utc(observed_at);state=collector.window_state(window,now)
    result=dict(execution_enabled=False,orders=0,automatic_promotion=False,
                prior_full_exposure_screen='FAIL_RETAINED',source_authenticity_attested=False)
    if state!='IN_WINDOW':return dict(result,status=state,network_requests=0)
    root=Path(root).resolve();closed=legacy.utc(window['formation_close']);deadline=legacy.utc(window['execution_open'])
    report=json.loads((root/'report.json').read_bytes())
    require(report['status']=='CAPTURED_PENDING_IDENTITY_REVIEW','CAPTURE_NOT_COMPLETE')
    manifest_blob=(root/'manifest.json').read_bytes();capture_hash=sha256(manifest_blob).hexdigest();manifest=json.loads(manifest_blob)
    require(report['manifest_sha256']==capture_hash,'CAPTURE_REPORT_BINDING')
    require(manifest['version']=='RC1' and manifest['window']==window and manifest['source_root']=='sources','CAPTURE_SCHEMA')
    require(manifest['legacy_RA1_compatible'] is False,'SOURCE_FORMAT_MISLABELLED')
    cohort_blob=(root/'cohort.json').read_bytes();cohort_hash=sha256(cohort_blob).hexdigest()
    require(cohort_hash==COHORT_HASH==manifest['cohort_sha256'],'COHORT_SEAL')
    cohort=json.loads(cohort_blob);names={row['symbol'] for row in cohort};allowed=names|{'SPY'}
    require(len(names)==len(cohort) and 'SOXL' not in allowed,'COHORT_SCOPE')
    registry.validate(list(aliases.values()),names)
    require(manifest['aliases']==aliases,'REGISTERED_ALIAS_BINDING')
    metadata_names=allowed|{row['lookup'] for row in aliases.values()}
    refs=manifest['source_refs'];bodies=[];paths=set()
    require(bool(refs),'NO_SOURCE_RECEIPTS')
    for ref in refs:
        require(ref['path'] not in paths,'DUPLICATE_SOURCE_PATH');paths.add(ref['path'])
        blob=read_ref(root/'sources',ref,metadata_names,now)
        require(closed<=legacy.utc(ref['request_started_at'])<=legacy.utc(ref['received_at'])<deadline,'SOURCE_NOT_IN_FORMATION_WINDOW')
        if ref['request']['kind'] in ('bars','actions'):
            require(set(ref['request']['params']['symbols'].split(','))<=allowed,'NONCANONICAL_PRICE_OR_ACTION_QUERY')
        bodies.append(blob)
    factor_blobs=[b for ref,b in zip(refs,bodies) if ref['request']['kind']=='factors']
    require(len(factor_blobs)==1,'FACTOR_RECEIPT_COUNT')
    factors=admission.factors(factor_blobs[0],window['formation'])
    import exchange_calendars as xc
    require(xc.__version__=='4.13.2','CALENDAR_VERSION')
    start=admission.month_shift(window['formation'][:7],-37)+'-01'
    calendar=[d.date().isoformat() for d in xc.get_calendar('XNYS').sessions_in_range(start,window['formation'])]
    data={}
    for adjustment in ('all','raw'):
        selected=[(ref,json.loads(b)) for ref,b in zip(refs,bodies)
            if ref['request']['kind']=='bars' and ref['request']['params']['adjustment']==adjustment]
        require(bool(selected),'PRICE_SNAPSHOT_MISSING')
        for ref,_ in selected:
            params=ref['request']['params'];require(params['start']==start and params['end']==window['formation'],'PRICE_WINDOW')
        rows,coverage=admission.pages_complete([r for r,b in selected],[b for r,b in selected],allowed,'bars')
        require(coverage==allowed,'FULL_UNIVERSE_QUERY_COVERAGE')
        require(sorted(rows.get('SPY',{}))==calendar,'BENCHMARK_CALENDAR')
        require(all(set(v)<=set(calendar) for v in rows.values()),'NONSESSION_BAR');data[adjustment]=rows
    adjusted={s:{d:v[0] for d,v in rows.items()} for s,rows in data['all'].items()};raw=data['raw']
    ranking=admission.load('aa_ranking','research/residual-shadow/ranking.py')
    rules=json.loads((ROOT/'docs/research/sector-momentum/protocol.json').read_bytes())
    residual=json.loads((ROOT/'docs/research/residual-momentum/protocol.json').read_bytes())
    computed=ranking.build(window['formation'],adjusted,raw,cohort,calendar,factors,rules,residual)
    seal_blob=(root/'candidate-rank-seal.json').read_bytes();seal=json.loads(seal_blob)
    require(seal['formation']==window['formation'] and seal['plans']==computed['plans'],'RANK_RECOMPUTATION_MISMATCH')
    require(seal['capture_manifest_sha256']==capture_hash and seal['execution_enabled'] is False,'RANK_CAPTURE_BINDING')
    latest=max(legacy.utc(ref['received_at']) for ref in refs);sealed=legacy.utc(seal['sealed_at'])
    require(latest<=sealed<=now and closed<=sealed<deadline,'RANK_SEAL_TIME')
    held=admission.verified_holdings(manifest['ledgers']['root'],manifest['ledgers']['heads'],now,collector.windows())
    require(held<=names,'HELD_SCOPE')
    base=ranking.parent.features(window['formation'],adjusted,raw,cohort,calendar,rules)
    required={r['symbol'] for r in base['base']}|held|{r['symbol'] for rows in computed['plans'].values() for r in rows}
    actions=[(ref,json.loads(b)) for ref,b in zip(refs,bodies) if ref['request']['kind']=='actions']
    if required:require(bool(actions),'ACTION_SNAPSHOT_MISSING')
    for ref,_ in actions:
        p=ref['request']['params']
        require(p['start']=='2025-04-25' and p['end']==now.date().isoformat()==legacy.utc(ref['received_at']).date().isoformat(),'ACTION_REVIEW_DATE')
    action_hashes=[ref['response_sha256'] for ref,b in actions]
    require(manifest['action_refs']==[ref for ref,b in actions],'ACTION_MANIFEST_BINDING')
    if actions:
        _,coverage=admission.pages_complete([r for r,b in actions],[b for r,b in actions],allowed,'actions')
        require(required<=coverage,'ACTION_COVERAGE')
    assets={}
    for ref,b in zip(refs,bodies):
        if ref['request']['kind']=='asset':
            lookup=ref['request']['params']['symbol'];require(lookup not in assets,'DUPLICATE_ASSET_SOURCE')
            assets[lookup]=(json.loads(b),ref)
    bindings={}
    for row in manifest['metadata_bindings']:
        symbol=row['canonical'];require(symbol not in bindings,'DUPLICATE_CANONICAL_BINDING')
        lookup=aliases[symbol]['lookup'] if symbol in aliases else symbol
        require(lookup in assets,'ASSET_SOURCE_MISSING');asset,ref=assets[lookup]
        expected=dict(registry.bind(symbol,asset,aliases,now.date()),source_response_sha256=ref['response_sha256'],source_path=ref['path'])
        require(row==expected,'METADATA_PROVENANCE_BINDING');bindings[symbol]=expected
    require(set(bindings)==required,'METADATA_SCOPE')
    require(set(assets)=={r['metadata_lookup'] for r in bindings.values()},'UNBOUND_ASSET_SOURCE')
    count=review_identity(root,reviews['identity_reviews'],bindings,required,action_hashes,capture_hash,
                          cohort_hash,closed,deadline,now,latest)
    require(reviews['capture_manifest_sha256']==capture_hash,'REVIEW_MANIFEST_BINDING')
    return dict(result,status='SHADOW_INPUTS_ADMISSIBLE',formation=window['formation'],
                capture_manifest_sha256=capture_hash,rank_seal_sha256=sha256(seal_blob).hexdigest(),
                review_manifest_sha256=sha256(canonical(reviews)).hexdigest(),
                audited_scores=computed['independently_checked_scores'],reviewed_identities=count,
                metadata_aliases=sum(row['alias_used'] for row in bindings.values()),
                source_responses_rewritten=False,journals_modified=False,
                clock_assumption='Trusted local receipt/review clock; no external timestamp attestation')
