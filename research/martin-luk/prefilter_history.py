"""Frozen MLP1 historical-data stage. Inputs and vendor responses stay private.

See docs/research/martin-luk/history.md for stage order and data limitations.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import sys,gzip,json,csv,collections,bisect
    from history_screen import split_adjust,necessary
    r=args.root
    import exchange_calendars as xc
    if xc.__version__!='4.13.2':raise ValueError('PINNED_CALENDAR_REQUIRED')
    xc.get_calendar('XNYS').schedule.loc['2024-08-01':'2025-12-31'].to_csv(r/'calendar.csv')
    cal=[]
    for row in csv.DictReader((r/'calendar.csv').open()):
     cal.append(dict(date=row[''].split(' ')[0],open=row['open'].replace(' ','T'),close=row['close'].replace(' ','T')))
    (r/'schedule.json').write_text(json.dumps(cal,indent=2)+'\n')
    actions=collections.defaultdict(list)
    for f in (r/'actions').glob('*.gz'):
     for k,rs in json.loads(gzip.decompress(f.read_bytes())).items():actions[k].extend(rs)
    dedup={}
    for k,rs in actions.items():
     d={}
     for a in rs:
      if a['id'] in d and a!=d[a['id']]:raise ValueError('CONFLICTING_ACTION')
      d[a['id']]=a
     dedup[k]=list(d.values())
    print('dedup actions',sum(map(len,actions.values())),sum(map(len,dedup.values())),flush=True)
    (r/'all-actions.json').write_text(json.dumps(dedup,separators=(',',':')))
    parent={}
    def find(s):
     parent.setdefault(s,s)
     if parent[s]!=s:parent[s]=find(parent[s])
     return parent[s]
    for a in dedup.get('name_changes',[]):parent[find(a['new_symbol'])]=find(a['old_symbol'])
    byroot=collections.defaultdict(list)
    for k in ('forward_splits','reverse_splits','stock_dividends'):
     for a in dedup.get(k,[]):
      a=dict(a)
      if k=='stock_dividends':a.update(old_rate=1,new_rate=a['rate'])
      byroot[find(a['symbol'])].append(a)
    metadata=json.loads((r/'cohort.json').read_text());splits={m['symbol']:byroot[find(m['symbol'])] for m in metadata}
    (r/'splits.json').write_text(json.dumps(splits,separators=(',',':')))
    results={s['date']:[] for s in cal if '2025-04-28'<=s['date']<='2025-12-31'}
    counts={d:collections.Counter() for d in results}
    lookup={m['symbol']:m for m in metadata}
    for f in sorted((r/'daily').glob('*.gz')):
     batch=json.loads(gzip.decompress(f.read_bytes()))
     for symbol,rows in batch.items():
      dated={b['t'][:10]:b for b in rows}
      for i,s in enumerate(cal):
       d=s['date']
       if d not in results:continue
       prior=cal[i-160:i]
       if len(prior)!=160 or any(x['date'] not in dated for x in prior):
        counts[d]['NO_COMPLETE_160_SESSION_HISTORY']+=1;continue
       bars=split_adjust([dated[x['date']] for x in prior],d,splits[symbol])
       reason=necessary(bars);counts[d][reason]+=1
       if reason=='NEEDS_RTH_HISTORY':results[d].append(symbol)
     print('prefiltered',f.name,flush=True)
    (r/'preselection.json').write_text(json.dumps(results,indent=2)+'\n')
    (r/'preselection-counts.json').write_text(json.dumps(counts,indent=2)+'\n')
    needed=sorted({s for ss in results.values() for s in ss})
    (r/'needed-symbols.json').write_text(json.dumps(needed,indent=2)+'\n')
    print('symbols_needing_RTH',len(needed),'candidate_days',sum(map(len,results.values())),'sessions',len(results),flush=True)


if __name__=='__main__':main()
