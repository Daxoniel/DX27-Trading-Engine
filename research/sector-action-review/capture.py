"""GET-only, cached evidence for the single public ETNB action incident.

No account endpoint, orders, 2026 prices, paid subscription or symbol search.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'martin-luk'))
from history_data import Cache


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    cache = Cache(a.output / 'pages')
    for quality in ('complete', 'all'):
        pages = list(cache.pages('/v1/corporate-actions', dict(symbols='ETNB',
            start='2025-09-01', end='2025-12-31', data_quality=quality, limit=1000, sort='asc')))
        (a.output / f'actions-{quality}.json').write_text(json.dumps(pages, indent=2))
    for adjustment in ('raw', 'all'):
        pages = list(cache.pages('/v2/stocks/bars', dict(symbols='ETNB', timeframe='1Day',
            start='2025-10-01', end='2025-11-05T23:59:59Z', adjustment=adjustment,
            asof='2025-04-25', feed='sip', sort='asc', limit=1000)))
        (a.output / f'bars-{adjustment}.json').write_text(json.dumps(pages, indent=2))
    print('Four evidence queries retained privately; no orders.')


if __name__ == '__main__':
    main()
