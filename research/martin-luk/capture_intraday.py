"""Frozen MLP1 historical-data stage. Inputs and vendor responses stay private.

See docs/research/martin-luk/history.md for stage order and data limitations.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import sys,json,gzip,time,threading
    from concurrent.futures import ThreadPoolExecutor,as_completed
    from urllib.error import HTTPError
    from history_data import Cache,bars
    r=args.root;selected=json.loads((r/'needed-symbols.json').read_text());pre=json.loads((r/'preselection.json').read_text());cal=json.loads((r/'schedule.json').read_text());days=[s['date'] for s in cal]
    lock=threading.Lock();clock=[0.]
    class Paced(Cache):
     def get(self,path,params):
      with lock:
       wait=max(0,clock[0]-time.monotonic());clock[0]=max(clock[0],time.monotonic())+.35
      if wait:time.sleep(wait)
      return super().get(path,params)
    c=Paced(r/'five-minute-pages')
    def fetch(pair):
     j,symbol=pair;p=r/'five-minute'/f'{symbol}.json.gz';p.parent.mkdir(exist_ok=True)
     if p.exists():return
     first=min(d for d,ss in pre.items() if symbol in ss);start=days[days.index(first)-160]
     for retry in range(8):
      try:result=bars(c,[symbol],'5Min',start,'2025-12-31T23:59:59Z');break
      except HTTPError as e:
       if e.code not in (429,502,503,504) or retry==7:raise
       print('retry_status',e.code,'symbol',symbol,flush=True);time.sleep(10)
     p.write_bytes(gzip.compress(json.dumps(result[symbol],separators=(',',':')).encode(),mtime=0))
     print('completed',symbol,'count',len(list((r/'five-minute').glob('*.gz'))),'of',len(selected),'bars',len(result[symbol]),flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
     for f in as_completed([pool.submit(fetch,x) for x in enumerate(selected)]):f.result()
    print('five-minute done',flush=True)


if __name__=='__main__':main()
