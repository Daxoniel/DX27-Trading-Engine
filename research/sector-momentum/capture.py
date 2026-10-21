"""GET-only adjusted-price features for the frozen sector-proxy study.

Prices and raw API bodies remain private. These are retrospective vendor
adjustments, not a point-in-time or executable-price certification.
"""
import argparse
from datetime import datetime,timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'martin-luk'))
from history_data import Cache


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    project=Path(__file__).resolve().parents[2]
    protocol_path=project/'docs/research/sector-momentum/protocol.json'
    protocol=json.loads(protocol_path.read_text());old=project/'work/mlp1-history'
    cohort_raw=(old/'cohort.json').read_bytes();schedule_raw=(old/'schedule.json').read_bytes()
    if sha256(cohort_raw).hexdigest()!=protocol['cohort_sha256']:raise ValueError('COHORT_SEAL_FAILED')
    if sha256(schedule_raw).hexdigest()!=protocol['schedule_sha256']:raise ValueError('CALENDAR_SEAL_FAILED')
    symbols=sorted({r['symbol'] for r in json.loads(cohort_raw)}|{'SPY'})
    a.output.mkdir(parents=True,exist_ok=True);dest=a.output/'adjusted';dest.mkdir(exist_ok=True)
    cache=Cache(a.output/'pages');refs=[]
    for i in range(0,len(symbols),50):
        names=symbols[i:i+50];out={s:[] for s in names};token=None;seen=set()
        while True:
            params=dict(symbols=','.join(names),timeframe='1Day',start=protocol['feature_capture_start'],
                end=protocol['feature_capture_end'],adjustment=protocol['feature_adjustment'],
                asof=protocol['security_asof'],feed=protocol['feed'],sort='asc',limit=10000)
            if token:params['page_token']=token
            for attempt in range(8):
                try:body=cache.get('/v2/stocks/bars',params);break
                except HTTPError as e:
                    if e.code not in (429,502,503,504) or attempt==7:raise
                    time.sleep(10)
            for s,rows in (body.get('bars') or {}).items():
                if s not in out:raise ValueError('UNREQUESTED_SYMBOL')
                out[s].extend(rows)
            token=body.get('next_page_token');time.sleep(.35)
            if not token:break
            if token in seen:raise ValueError('REPEATED_PAGE_TOKEN')
            seen.add(token)
        for rows in out.values():
            times=[r['t'] for r in rows]
            if times!=sorted(set(times)):raise ValueError('DUPLICATE_OR_UNSORTED_BARS')
        raw=json.dumps(out,sort_keys=True,separators=(',',':')).encode();name=f'adjusted/{i//50:03d}.json.gz'
        (a.output/name).write_bytes(gzip.compress(raw,mtime=0))
        refs.append(dict(path=name,sha256=sha256(raw).hexdigest(),rows=sum(len(v) for v in out.values()),symbols=len(names)))
        print('captured symbols',min(i+50,len(symbols)),'of',len(symbols),flush=True)
    raw_refs=[]
    for f in sorted((old/'daily').glob('*.json.gz')):
        raw=gzip.decompress(f.read_bytes());raw_refs.append(dict(path='../mlp1-history/daily/'+f.name,sha256=sha256(raw).hexdigest()))
    pages=[]
    for f in sorted((a.output/'pages').glob('*.meta.json')):
        m=json.loads(f.read_text());pages.append(dict(request_sha256=f.name.split('.')[0],sha256=m['sha256'],bytes=m['bytes']))
    manifest=dict(protocol_sha256=sha256(protocol_path.read_bytes()).hexdigest(),cohort_sha256=protocol['cohort_sha256'],
        schedule_sha256=protocol['schedule_sha256'],adjusted=refs,raw_daily=raw_refs,pages=pages,
        captured_at=datetime.now(timezone.utc).isoformat(),actual_orders=0)
    (a.output/'input-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
