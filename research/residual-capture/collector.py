"""Formation-window collection only; no admission, trades or legacy receipt rewriting."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import time

import registry
from source import Source,canonical,legacy,ROOT,read_ref
sys.path.insert(0,str(ROOT/'research/residual-admission'))
import admission

COHORT_HASH='eeadc8c0b4860640fd0a548301f9fb676cef7591168e04d10e98a479d6923d60'


def windows(): return json.loads((ROOT/'docs/research/residual-shadow/calendar.json').read_bytes())['planned_cycles']


def window_state(window,now):
    if window not in windows(): raise ValueError('UNREGISTERED_WINDOW')
    if now<legacy.utc(window['formation_close']):return 'BLOCKED_FORMATION_NOT_CLOSED'
    if now>=legacy.utc(window['execution_open']):return 'SKIP_CYCLE_INCOMPLETE'
    return 'IN_WINDOW'


def collect(root,window,cohort_blob,aliases,ledgers,clock,source_factory=Source):
    """Clock/transport injection is for labelled offline tests; CLI exposes neither."""
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    now=clock();status=window_state(window,now)
    result=dict(version='RC1',status=status,observed_at=now.isoformat(),formation=window['formation'],
                network_requests=0,stock_requests=0,new_rankings=0,execution_enabled=False,orders=0,
                automatic_promotion=False,prior_full_exposure_screen='FAIL_RETAINED')
    def report():
        with (root/'report.json').open('xb') as stream:stream.write(canonical(result)+b'\n')
        return result
    if status!='IN_WINDOW': return report()
    if sha256(cohort_blob).hexdigest()!=COHORT_HASH: raise ValueError('COHORT_SEAL')
    cohort=json.loads(cohort_blob);canonical_names={r['symbol'] for r in cohort};price_names=canonical_names|{'SPY'}
    if 'SOXL' in price_names or len(canonical_names)!=len(cohort):raise ValueError('COHORT_SCOPE')
    registry.validate(list(aliases.values()),canonical_names)
    (root/'cohort.json').write_bytes(cohort_blob)
    transport=source_factory(root/'sources',price_names|{r['lookup'] for r in aliases.values()})
    def get(kind,params):
        if isinstance(transport,Source):time.sleep(.35)
        if window_state(window,clock())!='IN_WINDOW':raise ValueError('CAPTURE_DEADLINE')
        # Transport can address the registered metadata alias; price and action
        # query scopes are separately limited to the immutable canonical cohort.
        if kind in ('bars','actions'):
            requested=set(params['symbols'].split(','))
            if not requested<=price_names:raise ValueError('NONCANONICAL_DATA_QUERY')
        result['network_requests']+=1
        if kind=='bars':result['stock_requests']+=1
        blob,ref=transport.get(kind,params)
        if read_ref(transport.root,ref,price_names|{r['lookup'] for r in aliases.values()},clock())!=blob:
            raise ValueError('TRANSPORT_BODY_BINDING')
        if window_state(window,clock())!='IN_WINDOW':raise ValueError('CAPTURE_DEADLINE')
        return blob,ref
    def pages(kind,params):
        refs=[];bodies=[];seen=set()
        for _ in range(1000):
            blob,ref=get(kind,params);body=json.loads(blob);refs.append(ref);bodies.append(body)
            if 'next_page_token' not in body:raise ValueError('PAGE_TERMINATOR')
            token=body['next_page_token']
            if token is None:return refs,bodies
            if not isinstance(token,str) or not token or token in seen:raise ValueError('PAGE_TOKEN')
            seen.add(token);params=dict(params,page_token=token)
        raise ValueError('PAGE_LIMIT')
    try:
        factor_blob,_=get('factors',{})
        try: factor_values=admission.factors(factor_blob,window['formation'])
        except ValueError as error:
            if str(error)!='FACTOR_MONTHS_MISSING':raise
            result['status']='BLOCKED_FACTOR_MONTHS_MISSING';return report()
        held=admission.verified_holdings(ledgers['root'],ledgers['heads'],clock(),windows())
        if not held<=canonical_names:raise ValueError('HELD_SCOPE')
        start=admission.month_shift(window['formation'][:7],-37)+'-01'
        import exchange_calendars as xc
        if xc.__version__!='4.13.2':raise ValueError('CALENDAR_VERSION')
        calendar=[d.date().isoformat() for d in xc.get_calendar('XNYS').sessions_in_range(start,window['formation'])]
        adjusted={};raw={};row_count=0;data_names=sorted(price_names)
        for adjustment in ('all','raw'):
            assembled={}
            for offset in range(0,len(data_names),50):
                names=data_names[offset:offset+50]
                params=dict(symbols=','.join(names),start=start,end=window['formation'],timeframe='1Day',
                            adjustment=adjustment,asof='2025-04-25',feed='sip',sort='asc',limit=10000)
                refs,bodies=pages('bars',params)
                data,coverage=admission.pages_complete(refs,bodies,price_names,'bars')
                if coverage!=set(names) or set(data)&set(assembled):raise ValueError('BATCH_COVERAGE')
                assembled.update(data);row_count+=sum(len(v) for v in data.values())
            if sorted(assembled.get('SPY',{}))!=calendar:raise ValueError('BENCHMARK_CALENDAR')
            if any(not set(rows)<=set(calendar) for rows in assembled.values()):raise ValueError('NONSESSION_BAR')
            if adjustment=='all':adjusted={s:{d:v[0] for d,v in rows.items()} for s,rows in assembled.items()}
            else:raw=assembled
        ranking=admission.load('rc_ranking','research/residual-shadow/ranking.py')
        rules=json.loads((ROOT/'docs/research/sector-momentum/protocol.json').read_bytes())
        residual=json.loads((ROOT/'docs/research/residual-momentum/protocol.json').read_bytes())
        ranked=ranking.build(window['formation'],adjusted,raw,cohort,calendar,factor_values,rules,residual)
        result['new_rankings']=1
        formation=ranking.parent.features(window['formation'],adjusted,raw,cohort,calendar,rules)
        required={r['symbol'] for r in formation['base']}|held|{r['symbol'] for rows in ranked['plans'].values() for r in rows}
        action_refs=[]
        names=sorted(required)
        for offset in range(0,len(names),50):
            params=dict(symbols=','.join(names[offset:offset+50]),start='2025-04-25',end=clock().date().isoformat(),data_quality='all',limit=1000)
            refs,bodies=pages('actions',params);admission.pages_complete(refs,bodies,price_names,'actions');action_refs.extend(refs)
        bindings=[]
        for symbol in names:
            row=aliases.get(symbol);lookup=row['lookup'] if row else symbol
            blob,ref=get('asset',dict(symbol=lookup));asset=json.loads(blob)
            binding=registry.bind(symbol,asset,aliases,clock().date())
            bindings.append(dict(binding,source_response_sha256=ref['response_sha256'],source_path=ref['path']))
        if window_state(window,clock())!='IN_WINDOW':raise ValueError('CAPTURE_DEADLINE')
        manifest=dict(version='RC1',window=window,cohort_sha256=COHORT_HASH,source_refs=transport.refs,
                      metadata_bindings=bindings,aliases=aliases,action_refs=action_refs,ledgers=ledgers,
                      identity_reviews=[],source_root='sources',legacy_RA1_compatible=False)
        with (root/'manifest.json').open('xb') as stream:stream.write(canonical(manifest)+b'\n')
        plan=dict(formation=window['formation'],plans=ranked['plans'],sealed_at=clock().isoformat(),
                  capture_manifest_sha256=sha256(canonical(manifest)+b'\n').hexdigest(),
                  status='CANDIDATE_RANKS_PENDING_IDENTITY_REVIEW',execution_enabled=False)
        with (root/'candidate-rank-seal.json').open('xb') as stream:stream.write(canonical(plan)+b'\n')
        result.update(status='CAPTURED_PENDING_IDENTITY_REVIEW',new_rankings=1,full_universe_queries=len(data_names),
                      total_price_rows=row_count,eligible_scores_audited=ranked['independently_checked_scores'],
                      metadata_bindings=len(bindings),metadata_aliases_used=sum(r['alias_used'] for r in bindings),
                      identity_reviews_complete=False,legacy_RA1_compatible=False,
                      manifest_sha256=sha256((root/'manifest.json').read_bytes()).hexdigest())
    except Exception as error:
        result.update(status='BLOCKED_CAPTURE_INCOMPLETE',failure_type=type(error).__name__,
                      failure_code=str(error) if isinstance(error,ValueError) else 'SOURCE_OR_IO_FAILURE')
    return report()


def verify_code():
    import decision
    decision.verify_code()
    public=ROOT/'docs/research/residual-capture';seal=json.loads((public/'code-seal.json').read_bytes())
    if sha256((public/'protocol.json').read_bytes()).hexdigest()!=seal['protocol_sha256']:raise ValueError('PROTOCOL_SEAL')
    for name,h in seal['files'].items():
        if sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=h:raise ValueError('CODE_SEAL')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--formation',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--registry',type=Path)
    p.add_argument('--ledgers',type=Path,help='JSON with root and heads for eight existing read-only journal directories')
    args=p.parse_args();verify_code()
    window=next((r for r in windows() if r['formation']==args.formation),None)
    if window is None:raise ValueError('UNREGISTERED_FORMATION')
    now=lambda:datetime.now(timezone.utc)
    # Before/after the window, even credentials/cohort/registry/ledger files are unnecessary.
    cohort=b'';aliases={};ledgers={}
    if window_state(window,now())=='IN_WINDOW':
        if args.registry is None or args.ledgers is None:p.error('--registry and --ledgers are required within the formation window')
        cohort=(ROOT/'work/mlp1-history/cohort.json').read_bytes()
        aliases=registry.load(args.registry,{r['symbol'] for r in json.loads(cohort)})
        ledgers=json.loads(args.ledgers.read_bytes())
    result=collect(args.output,window,cohort,aliases,ledgers,now)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
