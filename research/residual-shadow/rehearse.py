"""Offline rehydration of sealed RV1a snapshots; public engineering counts only."""
import argparse
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import ranking
from ledger import Journal, initialize, digest
from ledger_audit import audit

ROOT = ranking.ROOT


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_seals():
    for group,seal_name in [('sector-momentum','code-seal.json'),
                            ('residual-momentum','code-seal-v2.json'),
                            ('residual-validation','code-seal-v2.json')]:
        public = ROOT/'docs/research'/group
        seal = json.loads((public/seal_name).read_bytes())
        for name,h in seal.get('files',seal).items():
            require(sha256((ROOT/'research'/group/name).read_bytes()).hexdigest()==h,'PARENT_CODE_SEAL')
        if 'amendment_sha256' in seal:
            require(sha256((public/'input-amendment.json').read_bytes()).hexdigest()==seal['amendment_sha256'],
                    'PARENT_AMENDMENT_SEAL')
    own = json.loads((ROOT/'docs/research/residual-shadow/code-seal.json').read_bytes())
    for name,h in own['files'].items():
        require(sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==h,'SHADOW_CODE_SEAL')
    require(sha256((ROOT/'docs/research/residual-shadow/protocol.json').read_bytes()).hexdigest()==own['protocol_sha256'],
            'SHADOW_PROTOCOL_SEAL')


def inputs():
    v = ranking.load('rs_validation','research/residual-validation/validation.py')
    source = ROOT/'work/residual-validation'
    rules = json.loads((ROOT/'docs/research/residual-validation/protocol.json').read_bytes())
    original = json.loads((ROOT/'docs/research/sector-momentum/protocol.json').read_bytes())
    manifest_bytes = (source/'input-manifest.json').read_bytes(); manifest = json.loads(manifest_bytes)
    public_manifest = json.loads((ROOT/'docs/research/residual-validation/input-manifest.json').read_bytes())
    require(manifest==public_manifest,'PUBLIC_PRIVATE_MANIFEST_MISMATCH')
    # Public RV1a manifest seals the retained private input manifest.
    require(sha256((ROOT/'work/sector-momentum/input-manifest.json').read_bytes()).hexdigest()==rules['parent_manifest_sha256'],
            'SM1_MANIFEST_SEAL')
    require(manifest['protocol_sha256']==sha256((ROOT/'docs/research/residual-validation/protocol.json').read_bytes()).hexdigest(),
            'RV1_PROTOCOL_SEAL')
    adj,raw,cohort,old_calendar,_=v.rm.parent.load(ROOT/'work/sector-momentum/input-manifest.json',original)
    batches={k:v.read_batches(source,manifest['inputs'][k]) for k in ('adjusted_new','raw_new','history')}
    adj_new={s:{r['t'][:10]:r['c'] for r in rows} for s,rows in batches['adjusted_new'].items()}
    raw_new={s:{r['t'][:10]:(r['c'],r['v']) for r in rows} for s,rows in batches['raw_new'].items() if s!='SPY'}
    cal_bytes=(source/'calendar.json').read_bytes()
    require(sha256(cal_bytes).hexdigest()==manifest['calendar_sha256'],'CALENDAR_SEAL')
    expected=json.loads(cal_bytes); combined=sorted(set(old_calendar)|set(expected))
    formation_days=sorted({d[:7]:d for d in combined if rules['formation_start']<=d<=rules['formation_end']}.values())
    adj_new,blocked,_=v.quarantine_forward(adj,adj_new,combined,formation_days)
    for symbol in blocked:
        raw_new[symbol]={d:p for d,p in raw[symbol].items() if d.startswith('2025-12')}
    prices,_=v.join_forward(adj,adj_new); raw_prices,_=v.join_forward(raw,raw_new)
    history,_=v.rm.quarantine_unresolved(adj,batches['history'])
    prices,_=v.rm.extend_prices(prices,history)
    require([d for d in sorted(prices['SPY']) if d>='2025-12-01']==expected,'BENCHMARK_CALENDAR')
    blob=(source/'ff3.zip').read_bytes()
    require(sha256(blob).hexdigest()==manifest['factor_sha256']==rules['factor_file_sha256'],'FACTOR_SEAL')
    factors=v.read_factors(blob); calendar=sorted(prices['SPY'])
    for key in ('formation_start','formation_end','mark_end','initial_proxy_capital'):
        original[key]=rules[key]
    residual=json.loads((ROOT/'docs/research/residual-momentum/protocol.json').read_bytes())
    return prices,raw_prices,cohort,calendar,factors,original,residual,formation_days,sha256(manifest_bytes).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    verify_seals()
    prices,raw,cohort,calendar,factors,rules,residual,days,source_hash=inputs()
    plans=[]; base_count=0; score_count=0
    for day in days:
        plan=ranking.build(day,prices,raw,cohort,calendar,factors,rules,residual)
        plans.append(plan); base_count+=plan['independently_checked_features']; score_count+=plan['independently_checked_scores']
    (args.output/'rank-plans.json').write_text(json.dumps(plans,sort_keys=True)+'\n')
    cases={}; max_difference=0.
    # Compare target membership with immutable published study's private run ledgers.
    for selector in plans[0]['plans']:
        archived=json.loads((ROOT/f'work/residual-validation/{selector}-5bp.json').read_bytes())
        require(len(archived['events'])==len(plans),'ARCHIVED_EVENTS_COUNT')
        for plan,event in zip(plans,archived['events']):
            require(plan['asof']==event['formation'] and {r['symbol'] for r in plan['plans'][selector]}==set(event['weights']),
                    'ARCHIVED_TARGET_MISMATCH')
        execution={calendar[calendar.index(p['asof'])+2]:p for p in plans}
        sessions=[d for d in calendar if rules['formation_start']<=d<=rules['mark_end']]
        for bps in (5,25):
            key=f'{selector}-{bps}bp'; root=args.output/key; journal=Journal(root)
            journal.create(initialize(sessions,sorted(execution),bps))
            old_symbols=set()
            # Independent float reference uses unchanged parent solver, scaled slots only.
            transformed=[]
            for plan in plans:
                transformed.append(dict(asof=plan['asof'],eligible=[dict(row,momentum=0,beta=0) for row in plan['plans'][selector]]))
            proxy_rules=dict(rules,weight_per_slot=.01)
            reference=ranking.parent.run(prices,calendar,transformed,'ordinary',bps,proxy_rules)
            require(reference['summary']['halt'] is None,'REFERENCE_HALT')
            for day in sessions:
                plan=execution.get(day); rows=plan['plans'][selector] if plan else None
                required=old_symbols|{r['symbol'] for r in rows or []}
                request=dict(date=day,closes={s:prices.get(s,{}).get(day) for s in sorted(required)},source_sha256=source_hash)
                if plan:
                    request.update(targets=rows,rank_plan_sha256=digest(plan)); old_symbols={r['symbol'] for r in rows}
                journal.append(request)
            state,tail,_=journal.replay(); checked=audit(root)
            require(checked['complete'],'LEDGER_INCOMPLETE')
            # Daily NAV/cash/cost conservation compared to a separate float solver.
            for index,nav in enumerate(reference['nav'],start=1):
                mark=json.loads((root/f'{index:06d}.json').read_bytes())['mark']
                for field in ('nav','cash','gross'):
                    delta=abs(float(mark[field])-nav['equity' if field=='nav' else field])
                    require(delta<1e-7,'REFERENCE_ACCOUNT_MISMATCH');max_difference=max(max_difference,delta)
            cases[key]=dict(audit=checked,events=len(sessions)+1,tail_sha256=tail,
                            scheduled_rebalances=len(execution),source_snapshot_sha256=source_hash)
    result=dict(version='RS1',status='OFFLINE_COMPONENT_REHEARSAL_PASS',old_data_only=True,
                prospective_observations=0,new_prices_captured=False,prior_full_exposure_screen='FAIL_RETAINED',
                formations=len(plans),selectors=4,independent_base_checks=base_count,
                independent_score_checks=score_count,archived_target_sets_matched=len(plans)*4,
                cases=cases,maximum_float_reference_absolute_usd_difference=max_difference,
                actual_orders=0,broker_accessed=False,prospective_ready=False,automatic_promotion=False,
                blockers=['RF1_FORMATION_AND_REQUIRED_INPUTS_PENDING','IDENTITY_AND_CORPORATE_ACTION_REVIEW_REQUIRED',
                          'PROSPECTIVE_CAPTURE_AND_ADMISSION_NOT_IMPLEMENTED','NO_PERSISTENT_SCHEDULER'])
    (args.output/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))


if __name__=='__main__': main()
