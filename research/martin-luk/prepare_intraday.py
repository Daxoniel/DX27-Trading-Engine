"""Frozen MLP1 historical-data stage. Inputs and vendor responses stay private.

See docs/research/martin-luk/history.md for stage order and data limitations.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import sys,json,gzip,sqlite3,collections
    from history_screen import normalize_rth,aggregate
    from strategy import validate_bars,stamp
    r=args.root;cal=json.loads((r/'schedule.json').read_text())
    db=sqlite3.connect(r/'rth.sqlite');db.execute('CREATE TABLE IF NOT EXISTS bars(symbol TEXT,date TEXT,data BLOB,PRIMARY KEY(symbol,date))');db.execute('CREATE TABLE IF NOT EXISTS daily(symbol TEXT PRIMARY KEY,data TEXT)')
    known={x[0] for x in db.execute('SELECT symbol FROM daily')}
    for f in sorted((r/'five-minute').glob('*.gz')):
     s=f.stem.split('.')[0]
     if s in known:continue
     raw=json.loads(gzip.decompress(f.read_bytes()));days,cov=normalize_rth(raw,cal);daily={}
     for d,bs in days.items():
      if not bs:continue
      try:validate_bars(bs,stamp(bs[-1]['available_at']))
      except ValueError:cov[d]['complete']=False
      a=aggregate(bs);a.update(cov[d]);daily[d]=a
      db.execute('INSERT OR REPLACE INTO bars VALUES(?,?,?)',(s,d,gzip.compress(json.dumps(bs,separators=(',',':')).encode(),mtime=0)))
     db.execute('INSERT OR REPLACE INTO daily VALUES(?,?)',(s,json.dumps(daily,separators=(',',':'))));db.commit()
     print('prepared',s,'days',len(daily),'complete',sum(x['complete'] for x in daily.values()),flush=True)
    db.close();print('prepared existing files',flush=True)


if __name__=='__main__':main()
