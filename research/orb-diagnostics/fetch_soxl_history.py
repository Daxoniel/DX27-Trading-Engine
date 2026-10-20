"""Fixed-host, GET-only SIP source capture for the SOXL research protocol.

Private licensed bar payloads stay in work/. No broker endpoint or orders.
Uses only the Python standard library; rejects redirects and has no feed fallback.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('DATA_REDIRECT_REJECTED')


def fetch(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    opener = build_opener(NoRedirect())
    params = dict(timeframe='1Min', start='2015-12-01T00:00:00Z',
                  end='2026-01-01T00:00:00Z', limit=10000,
                  adjustment='split', feed='sip', sort='asc')
    headers = {'APCA-API-KEY-ID': os.environ['APCA_API_KEY_ID'],
               'APCA-API-SECRET-KEY': os.environ['APCA_API_SECRET_KEY']}
    manifest = dict(symbol='SOXL', feed='sip', adjustment='split',
                    request=params.copy(), pages=[], actual_orders=0)
    tokens = set()
    for page in range(1000):
        req = Request('https://data.alpaca.markets/v2/stocks/SOXL/bars?' +
                      urlencode(params), headers=headers, method='GET')
        try:
            with opener.open(req, timeout=45) as response:
                raw = response.read(8_000_001)
        except HTTPError as exc:
            raise RuntimeError('HISTORICAL_SIP_HTTP_' + str(exc.code)) from None
        if len(raw) > 8_000_000:
            raise ValueError('PAGE_TOO_LARGE')
        payload = json.loads(raw)
        if payload.get('symbol') != 'SOXL' or not isinstance(payload.get('bars'), list):
            raise ValueError('INVALID_SOXL_PAGE')
        name = f'page-{page:04}.json.gz'
        with gzip.GzipFile(filename=str(output / name), mode='wb', mtime=0) as stream:
            stream.write(raw)
        os.chmod(output / name, 0o600)
        manifest['pages'].append(dict(file=name, raw_sha256=hashlib.sha256(raw).hexdigest(),
                                     bars=len(payload['bars'])))
        manifest['captured_at'] = datetime.now(timezone.utc).isoformat()
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        if page % 20 == 0:
            print(json.dumps(dict(pages=page + 1, bars=sum(p['bars'] for p in manifest['pages']))), flush=True)
        token = payload.get('next_page_token')
        if token is None:
            manifest['complete'] = True
            (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print(json.dumps(dict(status='COMPLETE', pages=page + 1,
                                 bars=sum(p['bars'] for p in manifest['pages']))), flush=True)
            return
        if token in tokens:
            raise ValueError('REPEATED_PAGE_TOKEN')
        tokens.add(token)
        params['page_token'] = token
    raise ValueError('PAGE_BOUND_EXCEEDED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    fetch(parser.parse_args().output)
