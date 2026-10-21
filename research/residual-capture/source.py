"""GET-only RC1 transport: actual RFC3339 bar bounds retain separate declared dates."""
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,build_opener

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('rc_legacy_snapshots',ROOT/'research/residual-admission/snapshots.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
canonical=legacy.canonical


def request_spec(kind,params,allowed,today):
    result=legacy.request_spec(kind,params,allowed,today)
    if kind=='bars':
        actual=dict(params,start=params['start']+'T00:00:00Z',end=params['end']+'T23:59:59Z')
        result['api_params']=actual
        result['url']='https://data.alpaca.markets/v2/stocks/bars?'+urlencode(sorted(actual.items()))
    return result


class Source:
    def __init__(self,root,allowed):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.allowed=set(allowed);self.refs=[]
        if 'SOXL' in self.allowed: raise ValueError('RESERVED_SYMBOL')
        self.opener=build_opener(legacy.NoRedirect())

    def get(self,kind,params):
        started=datetime.now(timezone.utc).isoformat()
        req=request_spec(kind,params,self.allowed,datetime.now(timezone.utc).date())
        headers={'Accept-Encoding':'identity'}
        if kind!='factors': headers.update({'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],
                                           'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']})
        with self.opener.open(Request(req['url'],headers=headers,method='GET'),timeout=30) as response:
            if response.status!=200 or response.geturl()!=req['url']: raise ValueError('HTTP_RESPONSE')
            blob=response.read(25_000_001)
        if len(blob)>25_000_000: raise ValueError('RESPONSE_SIZE')
        filename=f'{len(self.refs):05d}.body'
        with (self.root/filename).open('xb') as stream: stream.write(blob)
        ref=dict(path=filename,request=req,request_sha256=sha256(canonical(req)).hexdigest(),
                 response_sha256=sha256(blob).hexdigest(),bytes=len(blob),http_status=200,
                 request_started_at=started,received_at=datetime.now(timezone.utc).isoformat(),source_format='RC1')
        with (self.root/f'{len(self.refs):05d}.receipt.json').open('xb') as stream:stream.write(canonical(ref)+b'\n')
        self.refs.append(ref)
        return blob,ref


def read_ref(root,ref,allowed,now):
    root=Path(root).resolve();path=(root/ref['path']).resolve()
    if path.parent!=root or path.suffix!='.body':raise ValueError('SOURCE_PATH')
    req=ref['request'];expected=request_spec(req['kind'],req['params'],allowed,now.date())
    if req!=expected or ref['request_sha256']!=sha256(canonical(req)).hexdigest():raise ValueError('SOURCE_REQUEST_SEAL')
    body=path.read_bytes()
    if ref.get('source_format')!='RC1' or ref['response_sha256']!=sha256(body).hexdigest() or ref['bytes']!=len(body) or ref['http_status']!=200:
        raise ValueError('SOURCE_RESPONSE_SEAL')
    if not legacy.utc(ref['request_started_at'])<=legacy.utc(ref['received_at'])<=now:raise ValueError('SOURCE_CLOCK')
    return body
