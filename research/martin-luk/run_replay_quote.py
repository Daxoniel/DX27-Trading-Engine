"""Quote-constrained MLP2 account diagnostic. No orders; exits remain OHLC proxies."""
import argparse
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path

from history_replay_quote import Replay
from quote_history_v2 import QuoteSource
from strategy import Rules, canonical


def replay_manifest(path, output, gap_policy='HALT', adverse_bps=5):
    path,output = Path(path),Path(output)
    manifest = json.loads(path.read_text())
    for name,digest in manifest['code_sha256'].items():
        if sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=digest:
            raise ValueError('REPLAY_CODE_SEAL_MISMATCH')
    code_seal=json.loads((Path(__file__).parents[2]/'docs/research/martin-luk/quote-code-seal.json').read_text())
    for name,digest in code_seal.items():
        if sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=digest:raise ValueError('QUOTE_CODE_SEAL_MISMATCH')
    quotes=QuoteSource(output.parent/'quote-pages')
    r = Replay(manifest['initial_cash'],Rules(version='MLP2',adverse_bps=adverse_bps),gap_policy,quotes)
    scans = []
    for ref in manifest['sessions']:
        raw = gzip.decompress((path.parent/ref['path']).read_bytes())
        if sha256(raw).hexdigest()!=ref['sha256']: raise ValueError('SESSION_SEAL_MISMATCH')
        s = json.loads(raw)
        plan = deepcopy(s['plan']);plan['rules']['adverse_bps'] = adverse_bps
        r.session(plan,s['bars'],s['daily_exit'],s['actions'])
        scans.append(dict(date=s['date'],watchlist=len(plan['watchlist'])))
        if len(scans)%10==0:print('processed',len(scans),'sessions','quote_requests',len(quotes.used),flush=True)
        if r.halt: break
    output.mkdir(parents=True,exist_ok=True)
    summary = dict(r.report(),provenance=manifest['provenance'],adverse_bps_each_side=adverse_bps,
        sessions_processed=len(scans),watchlist_stock_days=sum(s['watchlist'] for s in scans),
        input_manifest_sha256=sha256(path.read_bytes()).hexdigest(),
        quote_code_sha256=code_seal,quote_sources=list(quotes.used.values()),
        entry_quote_validated=True,exit_quote_validated=False)
    for name,body in dict(summary=summary,fills=r.fills,closed=r.closed,nav=r.nav,events=r.events,
            positions=r.positions,receivables=r.receivables,scans=scans).items():
        (output/(name+'.json')).write_text(canonical(body)+'\n')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gap-policy',choices=['HALT','OBSERVED_ONLY'],default='HALT')
    p.add_argument('--adverse-bps',type=float,choices=[5,10,25],default=5)
    a = p.parse_args()
    print(json.dumps(replay_manifest(a.manifest,a.output,a.gap_policy,a.adverse_bps)))
