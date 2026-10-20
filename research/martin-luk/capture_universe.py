"""Capture the pre-registered, third-party archived 2025-04-25 screener.

Publication history is evidence of availability, not vendor authentication or a
complete point-in-time security master. No current asset-status selection.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    a=p.parse_args();a.root.mkdir(parents=True,exist_ok=True)
    revision='adb5f855f29b023188f11abed0664648948da11f'
    url='https://api.github.com/gists/a481c4d2587e5600d2cc53e07a58e650/'+revision
    with urlopen(Request(url,headers={'Accept':'application/vnd.github+json'}),timeout=30) as r:raw=r.read()
    metadata=json.loads(raw)
    if metadata['updated_at']>'2025-04-26T00:00:00Z':raise ValueError('ARCHIVE_PUBLISHED_AFTER_ALLOWED_CUTOFF')
    file=metadata['files']['nasdaq_screener_04252025.csv']
    if not file['raw_url'].startswith('https://gist.githubusercontent.com/nickmccarty/'):
        raise ValueError('UNEXPECTED_ARCHIVE_HOST')
    with urlopen(file['raw_url'],timeout=30) as r:csv=r.read()
    if sha256(csv).hexdigest()!='8230a9b5f23eb91eb7b426ed40f08c81fbe9755f16ea41054471ee2369b8232a':
        raise ValueError('ARCHIVE_BYTES_CHANGED')
    (a.root/'universe-gist.json').write_bytes(raw)
    (a.root/'universe-20250425.csv').write_bytes(csv)
    print(json.dumps(dict(bytes=len(csv),sha256=sha256(csv).hexdigest(),revision=revision)))


if __name__=='__main__':main()
