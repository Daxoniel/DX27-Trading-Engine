"""Supplement frozen MLP2 candidate intraday coverage; GET-only, private cache.

Reuse earlier snapshots without silently replacing overlapping source values.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
from hashlib import sha256
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError

from history_data import Cache, bars
from strategy import canonical


def required_symbols(coverage):
    first = {}
    for ref in json.loads((coverage/'summary.json').read_text())['sessions_manifest']:
        raw = gzip.decompress((coverage/ref['path']).read_bytes())
        if sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('COVERAGE_PLAN_DIGEST_MISMATCH')
        p = json.loads(raw)
        for c in p['plans']['MLP2']['watchlist']:
            first.setdefault(c['symbol'],p['date'])
    first['SPY'] = '2025-04-28'
    return first


def merge_rows(old, new):
    indexed = {b['t']:b for b in old}
    if len(indexed) != len(old):
        raise ValueError('DUPLICATE_OLD_BAR')
    for b in new:
        if b['t'] in indexed and indexed[b['t']] != b:
            raise ValueError('OVERLAPPING_SOURCE_REVISION')
        indexed[b['t']] = b
    return [indexed[t] for t in sorted(indexed)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--coverage',type=Path,required=True)
    p.add_argument('--old-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    target = a.output/'five-minute'; target.mkdir(parents=True,exist_ok=True)
    lock = threading.Lock(); clock = [0.]
    class Paced(Cache):
        def get(self,path,params):
            with lock:
                delay = max(0,clock[0]-time.monotonic())
                clock[0] = max(clock[0],time.monotonic())+.35
            if delay: time.sleep(delay)
            for retry in range(8):
                try: return super().get(path,params)
                except HTTPError as e:
                    if e.code not in (429,502,503,504) or retry == 7: raise
                    time.sleep(10)
    cache = Paced(a.output/'pages')
    def fetch(pair):
        symbol,first = pair; dest = target/(symbol+'.json.gz')
        if dest.exists(): return
        old_path = a.old_root/'five-minute'/(symbol+'.json.gz')
        old = json.loads(gzip.decompress(old_path.read_bytes())) if old_path.exists() else []
        extra = []
        if not old:
            extra = bars(cache,[symbol],'5Min',first,'2025-12-31T23:59:59Z')[symbol]
        elif old[0]['t'][:10] > first:
            extra = bars(cache,[symbol],'5Min',first,old[0]['t'][:10]+'T00:00:00Z')[symbol]
        rows = merge_rows(old,extra)
        raw = canonical(rows).encode()
        dest.write_bytes(gzip.compress(raw,mtime=0))
        (target/(symbol+'.receipt.json')).write_text(canonical(dict(symbol=symbol,
            required_start=first,old_file_sha256=sha256(old_path.read_bytes()).hexdigest() if old_path.exists() else None,
            normalized_raw_sha256=sha256(raw).hexdigest(),rows=len(rows),new_rows=len(extra)))+'\n')
        print('captured',symbol,'new_rows',len(extra),flush=True)
    first = required_symbols(a.coverage)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(fetch,x) for x in sorted(first.items())]): f.result()
    benchmark_actions = {}
    for page in cache.pages('/v1/corporate-actions',dict(symbols='SPY',start='2025-04-01',
            end='2026-01-31',limit=1000,sort='asc')):
        for kind,records in page.get('corporate_actions',{}).items():
            benchmark_actions.setdefault(kind,[]).extend(records)
    (a.output/'SPY-actions.json').write_text(canonical(benchmark_actions)+'\n')
    (a.output/'required-symbols.json').write_text(canonical(first)+'\n')
    print('complete',len(first),'symbols',flush=True)


if __name__ == '__main__': main()
