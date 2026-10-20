"""Frozen MLP1 historical-data stage. Inputs and vendor responses stay private.

See docs/research/martin-luk/history.md for stage order and data limitations.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import sys,json,gzip
    from history_data import Cache,cohort
    r=args.root;names=cohort(r/'universe-20250425.csv');c=Cache(r/'action-pages')
    for i in range(0,len(names),200):
     p=r/'actions'/f'{i:04}.json.gz';p.parent.mkdir(exist_ok=True)
     if p.exists():continue
     out={}
     for page in c.pages('/v1/corporate-actions',dict(symbols=','.join(x['symbol'] for x in names[i:i+200]),start='2024-08-01',end='2026-01-31',limit=1000,sort='asc')):
      for k,rows in page['corporate_actions'].items():out.setdefault(k,[]).extend(rows)
     p.write_bytes(gzip.compress(json.dumps(out,separators=(',',':')).encode(),mtime=0))
     print('action_batch',i,'records',sum(len(v) for v in out.values()),flush=True)
    print('actions done',flush=True)


if __name__=='__main__':main()
