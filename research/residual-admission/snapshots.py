"""Bounded GET-only source snapshots. No orders/account endpoints or cache reuse."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

FACTOR_URL='https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def stamp(): return datetime.now(timezone.utc).isoformat()


def utc(value):
    value=datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset().total_seconds()!=0:
        raise ValueError('UTC_REQUIRED')
    return value


def names(value, allowed):
    rows=value.split(',')
    if not rows or len(rows)>50 or len(rows)!=len(set(rows)) or any(
            not re.fullmatch('[A-Z]+',s) or s=='SOXL' or s not in allowed for s in rows):
        raise ValueError('SYMBOL_SCOPE')
    return rows


def request_spec(kind, params, allowed, today):
    params=dict(params)
    if kind=='factors':
        if params: raise ValueError('FACTOR_PARAMS')
        return dict(method='GET',url=FACTOR_URL,kind=kind,params={})
    if kind=='asset':
        if set(params)!={'symbol'}: raise ValueError('ASSET_PARAMS')
        name=names(params['symbol'],allowed)
        if len(name)!=1: raise ValueError('ONE_ASSET_REQUIRED')
        url='https://paper-api.alpaca.markets/v2/assets/'+name[0]
    else:
        required={'symbols','start','end'}
        optional={'page_token'}
        if kind=='actions':
            required|={'data_quality','limit'}
            if params.get('data_quality')!='all' or params.get('limit')!=1000:
                raise ValueError('ACTION_SCOPE')
            path='/v1/corporate-actions'
        elif kind=='bars':
            required|={'timeframe','adjustment','asof','feed','sort','limit'}
            if (params.get('timeframe')!='1Day' or params.get('adjustment') not in ('all','raw')
                or params.get('asof')!='2025-04-25' or params.get('feed')!='sip'
                or params.get('sort')!='asc' or params.get('limit')!=10000):
                raise ValueError('BAR_SCOPE')
            path='/v2/stocks/bars'
        else: raise ValueError('ENDPOINT_NOT_ALLOWED')
        if not required<=set(params) or set(params)-required-optional:
            raise ValueError('QUERY_SCOPE')
        names(params['symbols'],allowed)
        start=date.fromisoformat(params['start']); end=date.fromisoformat(params['end'])
        if start>end or end>today or start<date(2022,1,1):
            raise ValueError('DATE_SCOPE')
        if 'page_token' in params and (not isinstance(params['page_token'],str) or not params['page_token']):
            raise ValueError('INVALID_PAGE_TOKEN')
        url='https://data.alpaca.markets'+path+'?'+urlencode(sorted(params.items()))
    return dict(method='GET',url=url,kind=kind,params=params)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError('REDIRECT_REJECTED')


class Capture:
    def __init__(self,root,allowed):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=False)
        self.allowed=set(allowed)
        if 'SOXL' in self.allowed: raise ValueError('RESERVED_SYMBOL')
        self.opener=build_opener(NoRedirect()); self.refs=[]

    def get(self,kind,params):
        spec=request_spec(kind,params,self.allowed,datetime.now(timezone.utc).date())
        request_bytes=canonical(spec); started=stamp(); headers={'Accept-Encoding':'identity'}
        if kind!='factors':
            headers.update({'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],
                            'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']})
        # No exception text/body is printed: may contain provider or request details.
        with self.opener.open(Request(spec['url'],headers=headers,method='GET'),timeout=30) as response:
            if response.status!=200 or response.geturl()!=spec['url']:
                raise ValueError('UNEXPECTED_RESPONSE')
            body=response.read(25_000_001)
        ended=stamp()
        if len(body)>25_000_000: raise ValueError('RESPONSE_TOO_LARGE')
        index=len(self.refs); filename=f'{index:04d}.body'
        with (self.root/filename).open('xb') as stream: stream.write(body)
        ref=dict(path=filename,request=spec,request_sha256=sha256(request_bytes).hexdigest(),
                 response_sha256=sha256(body).hexdigest(),bytes=len(body),
                 request_started_at=started,received_at=ended,http_status=200)
        with (self.root/f'{index:04d}.receipt.json').open('xb') as stream:
            stream.write(canonical(ref)+b'\n')
        self.refs.append(ref)
        return body,ref

    def pages(self,kind,params):
        seen=set(); rows=[]; refs=[]
        for _ in range(1000):
            blob,ref=self.get(kind,params); body=json.loads(blob); rows.append(body); refs.append(ref)
            if 'next_page_token' not in body: raise ValueError('PAGE_TERMINATOR_MISSING')
            token=body['next_page_token']
            if token is None: return rows,refs
            if not isinstance(token,str) or not token or token in seen:
                raise ValueError('INVALID_OR_REPEATED_PAGE_TOKEN')
            seen.add(token);params=dict(params,page_token=token)
        raise ValueError('PAGE_LIMIT')


def read_ref(root, ref, allowed, now):
    root=Path(root).resolve(); path=(root/ref['path']).resolve()
    if path.parent!=root or path.suffix!='.body': raise ValueError('SNAPSHOT_PATH')
    spec=ref['request']
    expected=request_spec(spec['kind'],spec['params'],allowed,now.date())
    if spec!=expected or ref['request_sha256']!=sha256(canonical(spec)).hexdigest():
        raise ValueError('REQUEST_BINDING')
    body=path.read_bytes()
    if sha256(body).hexdigest()!=ref['response_sha256'] or len(body)!=ref['bytes'] or ref['http_status']!=200:
        raise ValueError('RESPONSE_BINDING')
    started=utc(ref['request_started_at']); ended=utc(ref['received_at'])
    if not started<=ended<=now: raise ValueError('RECEIPT_CHRONOLOGY')
    return body
