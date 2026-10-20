"""Read-only, resumable Alpaca history cache. Raw responses stay under work/.

The API asof identifies securities; it does not time-limit price adjustments.
Always request raw bars and account for effective corporate actions separately.
"""
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from strategy import canonical


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('AUTHENTICATED_REDIRECT_REJECTED')


class Cache:
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.opener=build_opener(NoRedirect())
        self.headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],
            'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY'],
            'Accept':'application/json','Accept-Encoding':'identity'}
        self.requests=0

    def get(self, path, params):
        if path not in ('/v2/stocks/bars','/v1/corporate-actions'):
            raise ValueError('HISTORY_GET_PATH_REQUIRED')
        url='https://data.alpaca.markets'+path+'?'+urlencode(sorted(params.items()))
        key=sha256(url.encode()).hexdigest();p=self.root/(key+'.json.gz')
        meta=self.root/(key+'.meta.json')
        if p.exists() and meta.exists():
            raw=gzip.decompress(p.read_bytes());record=json.loads(meta.read_text())
            if record['url']!=url or record['sha256']!=sha256(raw).hexdigest():
                raise ValueError('CACHED_RESPONSE_SEAL_MISMATCH')
            return json.loads(raw)
        req=Request(url,headers=self.headers,method='GET')
        with self.opener.open(req,timeout=45) as r:
            if r.status!=200 or r.geturl()!=url:raise ValueError('UNEXPECTED_HISTORY_RESPONSE')
            raw=r.read(25_000_001)
            if len(raw)>25_000_000:raise ValueError('HISTORY_RESPONSE_TOO_LARGE')
        body=json.loads(raw)
        p.write_bytes(gzip.compress(raw,mtime=0))
        record=dict(url=url,sha256=sha256(raw).hexdigest(),bytes=len(raw),
            retrieved_at=datetime.now(timezone.utc).isoformat())
        meta.write_text(canonical(record)+'\n')
        self.requests+=1
        if self.requests%20==0:print('downloaded_pages',self.requests,flush=True)
        return body

    def pages(self,path,params):
        token=None;seen=set()
        while True:
            p=dict(params)
            if token:p['page_token']=token
            body=self.get(path,p);yield body
            token=body.get('next_page_token')
            if not token:break
            if token in seen:raise ValueError('REPEATED_PAGE_TOKEN')
            seen.add(token)


def cohort(csv_path):
    raw=Path(csv_path).read_bytes()
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    chosen=[dict(symbol=r['Symbol'],sector=r['Sector'],name=r['Name']) for r in rows
        if r['Country']=='United States' and r['Sector'] and r['Symbol'].isascii()
        and r['Symbol'].isalpha() and ('common stock' in r['Name'].lower()
        or 'common shares' in r['Name'].lower())]
    if len({r['symbol'] for r in chosen})!=len(chosen):raise ValueError('DUPLICATE_COHORT_SYMBOL')
    return sorted(chosen,key=lambda r:r['symbol'])


def bars(cache,symbols,timeframe,start,end):
    out={s:[] for s in symbols}
    for page in cache.pages('/v2/stocks/bars',dict(symbols=','.join(symbols),
            timeframe=timeframe,start=start,end=end,adjustment='raw',asof='2025-04-25',
            feed='sip',limit=10000,sort='asc')):
        for symbol,rows in (page.get('bars') or {}).items():
            if symbol not in out:raise ValueError('UNREQUESTED_SYMBOL')
            out[symbol].extend(rows)
    for rows in out.values():
        times=[r['t'] for r in rows]
        if times!=sorted(set(times)):raise ValueError('DUPLICATE_OR_UNSORTED_HISTORY')
    return out
