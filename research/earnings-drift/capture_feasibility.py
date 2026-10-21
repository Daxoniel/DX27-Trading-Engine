"""GET-only schema pilot, not an earnings universe or a return backtest.

Raw responses stay in work/. Only Alpaca's fixed historical news endpoint
receives its credentials. Other requests are public SEC/official-demo requests.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('REDIRECT_REJECTED')


NEWS = dict(symbols='NVDA', start='2025-05-28T00:00:00Z',
            end='2025-05-30T00:00:00Z', limit=50, sort='asc', include_content='true')
PUBLIC = {
    'sec-submissions': 'https://data.sec.gov/submissions/CIK0001045810.json',
    'sec-eps': 'https://data.sec.gov/api/xbrl/companyconcept/CIK0001045810/us-gaap/EarningsPerShareDiluted.json',
    'alphavantage-ibm-demo': 'https://www.alphavantage.co/query?function=EARNINGS&symbol=IBM&apikey=demo',
    'alpaca-doc-index': 'https://docs.alpaca.markets/us/llms.txt',
}


def capture(root, name, url, headers=None):
    root=Path(root);root.mkdir(parents=True, exist_ok=True)
    data=root/(name+'.raw');meta=root/(name+'.meta.json')
    if meta.exists():
        m=json.loads(meta.read_text())
        if m['url']!=url:raise ValueError('REQUEST_BINDING_FAILED')
        if data.exists():
            raw=data.read_bytes()
            if sha256(raw).hexdigest()!=m.get('sha256'):raise ValueError('CACHE_SEAL_FAILED')
            return m,raw
        if m.get('http_status')==200:raise ValueError('SUCCESS_BODY_MISSING')
        return m,None
    m=dict(id=name, url=url, retrieved_at=datetime.now(timezone.utc).isoformat())
    req=Request(url, headers={'User-Agent':'DX27-Trading-Engine research audit (github.com/Daxoniel/DX27-Trading-Engine)',
        'Accept':'application/json, text/plain', **(headers or {})}, method='GET')
    raw=None
    try:
        with build_opener(NoRedirect()).open(req, timeout=35) as r:
            raw=r.read(12_000_001)
            if len(raw)>12_000_000:raise ValueError('RESPONSE_TOO_LARGE')
            m.update(http_status=r.status, content_type=r.headers.get('Content-Type'))
    except HTTPError as e:
        m.update(http_status=e.code, error='HTTP_ERROR')
    except Exception as e:
        m.update(error=type(e).__name__)
    if raw is not None:
        data.write_bytes(raw);m.update(bytes=len(raw), sha256=sha256(raw).hexdigest())
    meta.write_text(json.dumps(m, indent=2)+'\n')
    return m,raw


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True);a=p.parse_args()
    headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],
             'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']}
    token=None;seen=set();page=0
    while True:
        params=dict(NEWS)
        if token:params['page_token']=token
        name='alpaca-news' if page==0 else f'alpaca-news-{page:03d}'
        m,raw=capture(a.output,name,'https://data.alpaca.markets/v1beta1/news?'+urlencode(params),headers)
        print(name,m.get('http_status'),flush=True)
        if m.get('http_status')!=200 or raw is None:break
        token=json.loads(raw).get('next_page_token')
        if not token:break
        if token in seen:raise ValueError('REPEATED_PAGE_TOKEN')
        seen.add(token);page+=1;time.sleep(.4)
    for name,url in PUBLIC.items():
        m,_=capture(a.output,name,url);print(name,m.get('http_status'),flush=True)


if __name__=='__main__':main()
