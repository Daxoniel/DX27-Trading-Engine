"""Run preregistered matched 2x2 minute/reentry cells with one shared quote cache."""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path

from audit_quote_history import audit_quotes
from minute_factorial import Replay
from quote_history_v2 import QuoteSource
from strategy import Rules, canonical


def run(manifest_path,output,quotes,minutes,reentry,bps,gap_policy):
    manifest_path,output=Path(manifest_path),Path(output)
    manifest=json.loads(manifest_path.read_text());quotes.used={}
    r=Replay(minutes=minutes,reentry=reentry,cash=manifest['initial_cash'],
        rules=Rules(version='MLP2',adverse_bps=bps),gap_policy=gap_policy,quote_source=quotes)
    scans=[]
    for ref in manifest['sessions']:
        raw=gzip.decompress((manifest_path.parent/ref['path']).read_bytes())
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('SESSION_SEAL_MISMATCH')
        s=json.loads(raw);plan=deepcopy(s['plan']);plan['rules']['adverse_bps']=bps
        r.session(plan,s['bars'],s['daily_exit'],s['actions'],s['minute_bars'])
        scans.append(dict(date=s['date'],watchlist=len(plan['watchlist']),equity=r.equity()))
        if len(scans)%10==0:print(output.name,'sessions',len(scans),'quote_requests',len(quotes.used),flush=True)
        if r.halt:break
    output.mkdir(parents=True,exist_ok=True)
    summary=dict(r.report(),provenance=manifest['provenance'],adverse_bps_each_side=bps,
        sessions_processed=len(scans),input_manifest_sha256=sha256(manifest_path.read_bytes()).hexdigest(),
        quote_sources=list(quotes.used.values()),entry_quote_validated=True,exit_quote_validated=False,
        code_seal=json.loads((Path(__file__).parents[2]/'docs/research/martin-luk/minute-reentry-code-seal.json').read_text()),
        signal_attempt_prior_states=dict(Counter(e['prior_terminal_kind'] for e in r.events if e['kind']=='SIGNAL_ATTEMPT')))
    for name,body in dict(summary=summary,fills=r.fills,closed=r.closed,nav=r.nav,events=r.events,
            positions=r.positions,receivables=r.receivables,scans=scans).items():
        (output/(name+'.json')).write_text(canonical(body)+'\n')
    validation=audit_quotes(output,quotes.cache.root)
    (output/'independent-validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    print('finished',output.name,'return',summary['net_return'],'halt',summary['halt'],'audit',validation['status'],flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    seal=json.loads((Path(__file__).parents[2]/'docs/research/martin-luk/minute-reentry-code-seal.json').read_text())
    for name,digest in seal.items():
        if sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=digest:raise ValueError('FACTORIAL_CODE_SEAL_MISMATCH')
    q=QuoteSource(a.output/'quote-pages')
    # Cost, cell and completeness order are fixed before any outcomes.
    for bps in (5,25):
        for minutes,reentry in ((5,False),(1,False),(5,True),(1,True)):
            name=f'{minutes}m-'+('reentry' if reentry else 'single')+f'-{bps}bp'
            dest=a.output/name
            if (dest/'independent-validation.json').exists():
                # Resume only if the ledger and all raw quote evidence still audit.
                previous=json.loads((dest/'summary.json').read_text())
                if (previous['code_seal']!=seal or previous['input_manifest_sha256']!=sha256(a.manifest.read_bytes()).hexdigest()
                        or previous['signal_minutes']!=minutes or previous['reentry']!=reentry
                        or previous['adverse_bps_each_side']!=bps):raise ValueError('CACHED_RUN_CONFIGURATION_MISMATCH')
                audit_quotes(dest,q.cache.root);print('verified cached run',name,flush=True);continue
            run(a.manifest,dest,q,minutes,reentry,bps,'OBSERVED_ONLY')
    for minutes,reentry in ((5,False),(1,False),(5,True),(1,True)):
        name=f'{minutes}m-'+('reentry' if reentry else 'single')+'-strict'
        run(a.manifest,a.output/name,q,minutes,reentry,5,'HALT')


if __name__=='__main__':main()
