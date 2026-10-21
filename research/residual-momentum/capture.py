"""GET-only historical extension and public FF3 ZIP; retained inputs stay private."""
import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT/'research/martin-luk'))
from history_data import Cache, NoRedirect


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); protocol_path = PROJECT/'docs/research/residual-momentum/protocol.json'
    rules = json.loads(protocol_path.read_text()); raw = (a.source/'formations.json').read_bytes()
    assert sha256(raw).hexdigest() == rules['parent_formations_sha256']
    symbols = sorted({r['symbol'] for f in json.loads(raw) for r in f['eligible']} | {'SPY'})
    assert len(symbols) == 347
    a.output.mkdir(parents=True, exist_ok=True); (a.output/'extension').mkdir(exist_ok=True)
    cache = Cache(a.output/'pages'); refs = []
    for i in range(0, len(symbols), 50):
        names = symbols[i:i+50]; rows = {s: [] for s in names}; token = None; seen = set()
        while True:
            params = dict(symbols=','.join(names), timeframe='1Day', start=rules['capture_start'],
                end=rules['capture_end'], adjustment=rules['capture_adjustment'],
                asof=rules['capture_asof'], feed='sip', sort='asc', limit=10000)
            if token:
                params['page_token'] = token
            for attempt in range(6):
                try:
                    body = cache.get('/v2/stocks/bars', params); break
                except HTTPError as error:
                    if error.code not in (429, 502, 503, 504) or attempt == 5:
                        raise
                    time.sleep(10)
            for s, bars in (body.get('bars') or {}).items():
                if s not in rows:
                    raise ValueError('UNREQUESTED_SYMBOL')
                rows[s].extend(bars)
            token = body.get('next_page_token'); time.sleep(.35)
            if not token:
                break
            if token in seen:
                raise ValueError('REPEATED_PAGE_TOKEN')
            seen.add(token)
        for bars in rows.values():
            dates = [b['t'] for b in bars]
            if dates != sorted(set(dates)):
                raise ValueError('DUPLICATE_OR_UNSORTED_BARS')
        raw = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
        name = f'extension/{i//50:03d}.json.gz'
        (a.output/name).write_bytes(gzip.compress(raw, mtime=0))
        refs.append(dict(path=name, sha256=sha256(raw).hexdigest(), symbols=len(rows), rows=sum(map(len, rows.values()))))
        print('captured', min(i+50, len(symbols)), 'of', len(symbols), flush=True)
    factor_path = a.output/'ff3.zip'; factor_meta = a.output/'ff3.meta.json'
    if factor_path.exists():
        meta = json.loads(factor_meta.read_text())
        assert meta['url'] == rules['factor_url'] and meta['sha256'] == sha256(factor_path.read_bytes()).hexdigest()
    else:
        with build_opener(NoRedirect()).open(Request(rules['factor_url'], method='GET'), timeout=45) as response:
            assert response.status == 200 and response.geturl() == rules['factor_url']
            raw = response.read(5_000_001)
        assert len(raw) <= 5_000_000 and raw.startswith(b'PK')
        factor_path.write_bytes(raw)
        factor_meta.write_text(json.dumps(dict(url=rules['factor_url'], sha256=sha256(raw).hexdigest(),
            bytes=len(raw), retrieved_at=datetime.now(timezone.utc).isoformat()), indent=2)+'\n')
    pages = []
    for path in sorted((a.output/'pages').glob('*.meta.json')):
        meta = json.loads(path.read_text())
        pages.append(dict(request_sha256=path.name.split('.')[0],
            **{k: meta[k] for k in ('sha256', 'bytes', 'retrieved_at')}))
    manifest = dict(protocol_sha256=sha256(protocol_path.read_bytes()).hexdigest(),
        parent_manifest_sha256=rules['parent_manifest_sha256'], extension=refs, pages=pages,
        factors=json.loads(factor_meta.read_text()), symbols=len(symbols),
        captured_at=datetime.now(timezone.utc).isoformat(), actual_orders=0)
    (a.output/'input-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()
