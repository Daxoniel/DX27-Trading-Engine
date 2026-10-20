"""Read-only raw SIP minutes for every frozen candidate opening window."""
import argparse
from datetime import timedelta
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time
from urllib.error import HTTPError

from history_data import Cache, bars
from strategy import canonical, stamp


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    class Paced(Cache):
        clock=0.
        def get(self,path,params):
            for retry in range(8):
                delay=max(0,self.clock-time.monotonic())
                if delay:time.sleep(delay)
                self.clock=time.monotonic()+.35
                try:return super().get(path,params)
                except HTTPError as e:
                    if e.code not in (429,502,503,504) or retry==7:raise
                    time.sleep(10)
    cache=Paced(a.output/'minute-pages');refs=[]
    for ref in json.loads(a.manifest.read_text())['sessions']:
        raw=gzip.decompress((a.manifest.parent/ref['path']).read_bytes())
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('BASE_SESSION_SEAL_MISMATCH')
        s=json.loads(raw);date=s['date'];file=a.output/(date+'.minutes.json.gz')
        if file.exists():data=gzip.decompress(file.read_bytes())
        else:
            plan=s['plan'];opening=stamp(plan['session_open'])
            symbols=[c['symbol'] for c in plan['watchlist']]
            rows=bars(cache,symbols,'1Min',opening.isoformat(),(opening+timedelta(minutes=125)).isoformat())
            data=canonical(dict(date=date,bars=rows)).encode()
            file.write_bytes(gzip.compress(data,mtime=0))
        refs.append(dict(path=file.name,sha256=sha256(data).hexdigest()))
        print('captured',date,flush=True)
    (a.output/'minutes-manifest.json').write_text(canonical(dict(
        base_manifest_sha256=sha256(a.manifest.read_bytes()).hexdigest(),sessions=refs))+'\n')


if __name__=='__main__':main()
