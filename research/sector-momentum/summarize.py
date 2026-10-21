"""Publish aggregate diagnostics only; private prices, selections and ledgers stay private."""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from study import load
from audit import verify_features,audit_case


def attribution(case,adj,sectors):
    events={e['date']:e for e in case['events']};units={};previous={};pnl=defaultdict(float)
    max_name=0.;max_sector=0.
    for n in case['nav']:
        d=n['date'];values={s:q*adj[s][d] for s,q in units.items()}
        for s,v in values.items():pnl[s]+=v-previous[s]
        if d in events:
            values=events[d]['new_values'];units={s:v/adj[s][d] for s,v in values.items()}
        previous=values;groups=defaultdict(float)
        for s,v in values.items():groups[sectors.get(s,'BENCHMARK')]+=v
        max_name=max(max_name,max(values.values(),default=0)/n['equity'])
        max_sector=max(max_sector,max(groups.values(),default=0)/n['equity'])
    if abs(sum(pnl.values())-case['summary']['modeled_cost']-(case['nav'][-1]['equity']-100000))>.001:
        raise ValueError('ATTRIBUTION_RECONCILIATION_FAILED')
    gains=sorted((v for v in pnl.values() if v>0),reverse=True);positive=sum(gains)
    return dict(top_one_share_of_positive_dollar_contribution=gains[0]/positive if positive else None,
        top_three_share_of_positive_dollar_contribution=sum(gains[:3])/positive if positive else None,
        unique_selected_names=len(set().union(*(e['weights'] for e in case['events']))) if case['events'] else 0,
        maximum_drifted_single_name_weight=max_name,maximum_drifted_sector_weight=max_sector,
        attribution_note='Observed-path dollar changes, not a leave-one-name-out counterfactual or executed-trade P&L.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    folder=Path(__file__).resolve().parents[2]/'docs/research/sector-momentum'
    rules=json.loads((folder/'protocol.json').read_text());seal=json.loads((folder/'code-seal.json').read_text())
    adj,raw,cohort,calendar,manifest=load(a.root/'input-manifest.json',rules)
    formations=json.loads((a.root/'formations.json').read_text());checked=verify_features(formations,adj,raw,calendar,rules)
    sectors={r['symbol']:r['sector'] for r in cohort};runs={};private={}
    digest=sha256((a.root/'input-manifest.json').read_bytes()).hexdigest()
    for bps in (5,25):
        for mode in ('ordinary','relative','broad','spy'):
            name=mode+f'-{bps}bp';path=a.root/(name+'.json');r=json.loads(path.read_text());private[name]=r
            validation=audit_case(path,adj,calendar,formations,rules,digest,seal)
            runs[name]=dict(summary=r['summary'],independent_validation=validation,nav=r['nav'],intervals=r['intervals'],
                attribution=attribution(r,adj,sectors),private_artifact_sha256=sha256(path.read_bytes()).hexdigest(),
                mean_formation_weighted_beta=mean(e['ex_ante_weighted_beta'] for e in r['events']) if r['events'] else None)
            print('audited',name,flush=True)
    overlaps=[]
    for x,y in zip(private['ordinary-5bp']['events'],private['relative-5bp']['events']):
        overlaps.append(dict(formation=x['formation'],ordinary_names=len(x['weights']),relative_names=len(y['weights']),
            common_names=len(set(x['weights'])&set(y['weights']))))
    contrasts={}
    for bps in (5,25):
        o=runs[f'ordinary-{bps}bp']['summary'];r=runs[f'relative-{bps}bp']['summary']
        contrasts[str(bps)]=dict(relative_minus_ordinary_return_pp=None if o['halt'] or r['halt'] else 100*(r['proxy_return']-o['proxy_return']))
    coverage=[dict(date=f['asof'],base_names=len(f['base']),high_beta_with_peers=len(f['eligible']),rejections=f['rejections']) for f in formations]
    result=dict(runs=runs,contrasts=contrasts,paired_name_overlap=overlaps,formation_coverage=coverage,
        eligible_features_independently_checked=checked,private_formations_sha256=sha256((a.root/'formations.json').read_bytes()).hexdigest(),
        input_manifest_sha256=digest,actual_orders=0,independent_out_of_sample=False,execution_validated=False,promotable=False)
    (a.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'input-manifest.json').write_bytes((a.root/'input-manifest.json').read_bytes())


if __name__=='__main__':main()
