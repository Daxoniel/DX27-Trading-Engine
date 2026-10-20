"""GET-only historical quote cache and conservative displayed-ask entry model."""
from datetime import timedelta
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from history_data import Cache
from strategy import canonical, stamp


def nanos(value):
    """Preserve sub-microsecond quote precision when enforcing no future data."""
    value=value.replace('Z','+00:00')
    if '.' in value:
        base,rest=value.split('.',1);fraction,zone=rest.split('+',1)
        if zone!='00:00' or not fraction.isdigit() or len(fraction)>9:
            raise ValueError('UTC_NANOSECOND_TIMESTAMP_REQUIRED')
        base+='+00:00'
    else:base=value;fraction=''
    return int(stamp(base).timestamp())*1_000_000_000+int(fraction.ljust(9,'0') or '0')


def quote_fill(quote, at, intent, bps):
    if not quote:return None,'QUOTE_MISSING'
    age=nanos(at)-nanos(quote['t'])
    if not 0<=age<=60_000_000_000:return None,'QUOTE_FUTURE_OR_STALE'
    bid,ask,size=quote['bp'],quote['ap'],quote['as']
    if (not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (bid,ask,size))
            or bid>ask or quote.get('c')!=['R']):return None,'QUOTE_NONREGULAR_OR_INVALID'
    if ask>250:return None,'ROUND_LOT_SIZE_UNVERIFIED'
    price=ask*(1+bps/10000)
    if price>intent['limit_price']:return None,'ASK_WITH_COST_ABOVE_LIMIT'
    if price<=intent['stop_price']:return None,'ASK_ALREADY_BELOW_PROTECTION'
    quantity=min(intent['quantity'],math.floor(size*100))
    if quantity<=0:return None,'NO_DISPLAYED_ASK_CAPACITY'
    return dict(price=price,quantity=quantity,reference_ask=ask,quote_at=quote['t'],
        visible_ask_shares=math.floor(size*100),unfilled_cancelled=intent['quantity']-quantity),None


class QuoteSource:
    def __init__(self, root):
        self.cache=Cache(root);self.next_request=0.;self.used={}

    def __call__(self,symbol,at):
        if not symbol.isascii() or not symbol.isalpha():raise ValueError('PLAIN_SYMBOL_REQUIRED')
        params=dict(symbols=symbol,start=(stamp(at)-timedelta(seconds=60)).isoformat(),
            end=at,feed='sip',asof='2025-04-25',sort='desc',limit=1)
        url='https://data.alpaca.markets/v2/stocks/quotes?'+urlencode(sorted(params.items()))
        key=sha256(url.encode()).hexdigest();file=self.cache.root/(key+'.json.gz');meta=file.with_name(key+'.meta.json')
        if file.exists() and meta.exists():
            raw=gzip.decompress(file.read_bytes());record=json.loads(meta.read_text())
            if record['url']!=url or record['sha256']!=sha256(raw).hexdigest():raise ValueError('QUOTE_CACHE_SEAL_MISMATCH')
        else:
            for retry in range(8):
                delay=max(0,self.next_request-time.monotonic())
                if delay:time.sleep(delay)
                self.next_request=time.monotonic()+.35
                try:
                    with self.cache.opener.open(Request(url,headers=self.cache.headers,method='GET'),timeout=45) as response:
                        if response.geturl()!=url:raise ValueError('QUOTE_REDIRECT_REJECTED')
                        raw=response.read(1_000_001)
                    if len(raw)>1_000_000:raise ValueError('QUOTE_RESPONSE_TOO_LARGE')
                    break
                except HTTPError as e:
                    if e.code not in (429,502,503,504) or retry==7:raise
                    time.sleep(10)
            record=dict(url=url,sha256=sha256(raw).hexdigest(),bytes=len(raw))
            file.write_bytes(gzip.compress(raw,mtime=0));meta.write_text(canonical(record)+'\n')
        self.used[key]=dict(sha256=record['sha256'],bytes=record['bytes'])
        body=json.loads(raw);rows=(body.get('quotes') or {}).get(symbol,[])
        if len(rows)>1:raise ValueError('LATEST_QUOTE_LIMIT_NOT_RESPECTED')
        return rows[0] if rows else None
