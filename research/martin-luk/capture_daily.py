"""Frozen MLP1 historical-data stage. Inputs and vendor responses stay private.

See docs/research/martin-luk/history.md for stage order and data limitations.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import sys,json,gzip,hashlib
    from history_data import Cache,bars,cohort
    root=args.root; names=cohort(root/'universe-20250425.csv')
    (root/'cohort.json').write_text(json.dumps(names,indent=2)+'\n')
    c=Cache(root/'daily-pages')
    count=0
    for i in range(0,len(names),100):
        output=root/'daily'/f'{i:04}.json.gz';output.parent.mkdir(exist_ok=True)
        if output.exists():continue
        part=bars(c,[r['symbol'] for r in names[i:i+100]],'1Day','2024-08-01','2025-12-31T23:59:59Z')
        output.write_bytes(gzip.compress(json.dumps(part,separators=(',',':')).encode(),mtime=0))
        count+=sum(len(x) for x in part.values())
        print('batch',i,'rows',sum(len(x) for x in part.values()),flush=True)
    print('done',len(names),count,flush=True)


if __name__=='__main__':main()
