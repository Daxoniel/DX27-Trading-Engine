"""Replay a normalized on-disk history manifest one session at a time.

python research/martin-luk/run_history.py --manifest PATH --output DIRECTORY
Raw vendor pages, normalized market bars and ledgers must remain private.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from history_replay import Replay
from strategy import Rules, canonical


def replay_manifest(manifest_path, output):
    manifest_path=Path(manifest_path);output=Path(output)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    here=Path(__file__).parent
    if hashlib.sha256((here/'strategy.py').read_bytes()).hexdigest()!=manifest['strategy_sha256']:
        raise ValueError('FROZEN_STRATEGY_SEAL_MISMATCH')
    rules=Rules(**manifest['rules']);replay=Replay(manifest['initial_cash'],rules)
    scans=[]
    for reference in manifest['sessions']:
        p=manifest_path.parent/reference['path']
        raw=gzip.decompress(p.read_bytes())
        if hashlib.sha256(raw).hexdigest()!=reference['sha256']:raise ValueError('SESSION_INPUT_SEAL_MISMATCH')
        s=json.loads(raw)
        replay.session(s['plan'],s['bars'],s['trails'],s['actions'])
        scans.append(dict(date=s['date'],watchlist=len(s['plan']['watchlist']),
            rejected=s['plan']['rejected'],warmup_exclusions=s['warmup_exclusions']))
        if replay.halt:break
    output.mkdir(parents=True,exist_ok=True)
    summary=dict(replay.report(),provenance=manifest['provenance'],
        sessions_processed=len(scans),watchlist_stock_days=sum(s['watchlist'] for s in scans),
        input_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    artifacts=dict(summary=summary,fills=replay.fills,closed=replay.closed,nav=replay.nav,
        events=replay.events,positions=replay.positions,receivables=replay.receivables,scans=scans)
    for name,body in artifacts.items():(output/(name+'.json')).write_text(canonical(body)+'\n',encoding='utf-8')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(replay_manifest(a.manifest,a.output),ensure_ascii=False))
