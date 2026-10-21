"""GET-only frozen non-SOXL history capture. No broker endpoint or orders."""
import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT/'research/martin-luk'))
from history_data import Cache


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); protocol_path = PROJECT/'docs/research/residual-validation/protocol.json'
    rules = json.loads(protocol_path.read_text()); source = PROJECT/'work/mlp1-history/cohort.json'
    assert sha256(source.read_bytes()).hexdigest() == rules['cohort_sha256']
    symbols = sorted({r['symbol'] for r in json.loads(source.read_text())}|{'SPY'})
    assert len(symbols) == 4003 and 'SOXL' not in symbols
    a.output.mkdir(parents=True, exist_ok=True); cache = Cache(a.output/'pages'); references = {}
    settings = [('adjusted_new', rules['capture_new'], 'all'),
                ('raw_new', rules['capture_new'], 'raw'),
                ('history', rules['capture_history'], 'all')]
    for kind, config, adjustment in settings:
        (a.output/kind).mkdir(exist_ok=True); refs = []
        for index in range(0, len(symbols), 50):
            names = symbols[index:index+50]; rows = {s: [] for s in names}
            token = None; seen = set()
            while True:
                params = dict(symbols=','.join(names), timeframe='1Day', start=config['start'],
                    end=config['end'], adjustment=adjustment, asof=config['asof'], feed='sip', sort='asc', limit=10000)
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
                times = [r['t'] for r in bars]
                if times != sorted(set(times)):
                    raise ValueError('DUPLICATE_OR_UNSORTED_BARS')
            raw = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
            filename = f'{kind}/{index//50:03d}.json.gz'
            (a.output/filename).write_bytes(gzip.compress(raw, mtime=0))
            refs.append(dict(path=filename, sha256=sha256(raw).hexdigest(), rows=sum(map(len, rows.values())), symbols=len(rows)))
            print(kind, min(index+50, len(symbols)), 'of', len(symbols), flush=True)
        references[kind] = refs
    import exchange_calendars as xc
    assert xc.__version__ == '4.13.2'
    dates = [d.date().isoformat() for d in xc.get_calendar('XNYS').sessions_in_range('2025-12-01', rules['mark_end'])]
    calendar = json.dumps(dates, indent=2).encode()+b'\n'; (a.output/'calendar.json').write_bytes(calendar)
    factors = (PROJECT/'work/residual-momentum/ff3.zip').read_bytes()
    assert sha256(factors).hexdigest() == rules['factor_file_sha256']
    (a.output/'ff3.zip').write_bytes(factors)
    pages = []
    for path in sorted((a.output/'pages').glob('*.meta.json')):
        meta = json.loads(path.read_text()); pages.append(dict(request_sha256=path.name.split('.')[0],
            **{k: meta[k] for k in ('sha256', 'bytes', 'retrieved_at')}))
    manifest = dict(protocol_sha256=sha256(protocol_path.read_bytes()).hexdigest(), source_cohort_sha256=rules['cohort_sha256'],
        inputs=references, calendar_sha256=sha256(calendar).hexdigest(), calendar_package='exchange_calendars 4.13.2 XNYS',
        factor_sha256=sha256(factors).hexdigest(), pages=pages, actual_orders=0,
        captured_at=datetime.now(timezone.utc).isoformat())
    (a.output/'input-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()
