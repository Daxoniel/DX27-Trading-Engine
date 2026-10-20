"""Frozen MLP1 historical-data stage. Inputs and vendor responses stay private.

See docs/research/martin-luk/history.md for stage order and data limitations.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    import sys,json,gzip,sqlite3,hashlib,collections
    from history_screen import final_plan,split_adjust
    from strategy import ema,Rules,canonical
    from dataclasses import asdict
    r=args.root;db=sqlite3.connect(r/'rth.sqlite');db.execute('CREATE INDEX IF NOT EXISTS by_date ON bars(date)');db.commit()
    cal=json.loads((r/'schedule.json').read_text());pre=json.loads((r/'preselection.json').read_text());meta={a['symbol']:a for a in json.loads((r/'cohort.json').read_text())};splits=json.loads((r/'splits.json').read_text())
    daily={s:json.loads(raw) for s,raw in db.execute('SELECT symbol,data FROM daily')}
    needed=set(json.loads((r/'needed-symbols.json').read_text()))
    if set(daily)!=needed:raise ValueError('RTH_DOWNLOAD_NOT_COMPLETE')
    source={}
    for f in (r/'daily').glob('*.gz'):
     for s,rows in json.loads(gzip.decompress(f.read_bytes())).items():
      if s in needed:source[s]={b['t'][:10]:b for b in rows}
    comparison=collections.Counter();maxdiff=collections.defaultdict(float)
    for s,ds in daily.items():
     for d,b in ds.items():
      if not b['complete'] or d not in source[s]:continue
      original=source[s][d];comparison['compared_stock_days']+=1
      for key in ('o','h','l','c'):
       diff=abs(b[key]-original[key])/max(original[key],1e-12);maxdiff[key]=max(maxdiff[key],diff)
       if diff>1e-8:comparison[key+'_different']+=1
    comparison=dict(comparison);comparison['max_relative_difference']=dict(maxdiff)
    (r/'daily-ohlc-comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
    allacts=json.loads((r/'all-actions.json').read_text());parent={}
    def find(s):
     parent.setdefault(s,s)
     if parent[s]!=s:parent[s]=find(parent[s])
     return parent[s]
    for a in allacts.get('name_changes',[]):parent[find(a['new_symbol'])]=find(a['old_symbol'])
    roots=collections.defaultdict(list)
    for s in meta:roots[find(s)].append(s)
    acts=[];unique=set()
    for kind,records in allacts.items():
     for a in records:
      if kind=='name_changes':continue
      sym=a.get('symbol') or a.get('source_symbol') or a.get('acquiree_symbol') or a.get('old_symbol')
      if not sym:continue
      for target in roots.get(find(sym),[]):
       k=(a['id'],target)
       if k in unique:continue
       unique.add(k);date=a.get('ex_date') or a.get('effective_date') or a.get('process_date')
       z=dict(id=a['id']+':'+target,symbol=target,date=date,kind=kind)
       if kind in ('forward_splits','reverse_splits'):z.update(kind='split',ratio=a['new_rate']/a['old_rate'])
       elif kind=='stock_dividends':z.update(kind='split',ratio=a['rate'])
       elif kind=='cash_dividends':
        if not a.get('payable_date') or a.get('rate') is None:z.update(kind='UNRESOLVED_CASH_DIVIDEND')
        else:z.update(kind='cash_dividend',rate=a['rate'],payable_date=a['payable_date'])
       acts.append(z)
    acts.sort(key=lambda a:(a['date'],0 if a['kind']=='split' else 1,a['id']))
    output=r/'normalized';output.mkdir(exist_ok=True);refs=[];counts=collections.Counter()
    for i,s in enumerate(cal):
     d=s['date']
     if d not in pre:continue
     prior=cal[i-160:i]
     p,excluded=final_plan(d,prior,s,[meta[n] for n in pre[d]],daily,splits)
     trails={}
     for symbol in needed:
      rows=[daily[symbol].get(x['date']) for x in prior]
      if len(rows)!=160 or any(b is None or not b['complete'] for b in rows):continue
      adjusted=split_adjust(rows,d,splits.get(symbol,[]));trails[symbol]=ema([b['c'] for b in adjusted],9)[-1]
     bs={symbol:json.loads(gzip.decompress(raw)) for symbol,raw in db.execute('SELECT symbol,data FROM bars WHERE date=?',(d,))}
     payload=dict(date=d,plan=p,bars=bs,trails=trails,actions=[a for a in acts if a['date']==d],warmup_exclusions=excluded)
     raw=canonical(payload).encode();name=d+'.json.gz';(output/name).write_bytes(gzip.compress(raw,mtime=0))
     refs.append(dict(path=name,sha256=hashlib.sha256(raw).hexdigest()))
     counts['watchlist_stock_days']+=len(p['watchlist']);counts['warmup_excluded_stock_days']+=len(excluded)
     for a in p['rejected']:counts[a['reason']]+=1
     print('built',d,'watchlist',len(p['watchlist']),'warmup_exclusions',len(excluded),flush=True)
    manifest=dict(strategy_sha256=hashlib.sha256(Path(__file__).with_name('strategy.py').read_bytes()).hexdigest(),rules=asdict(Rules()),initial_cash=100000,sessions=refs,provenance=dict(universe='ARCHIVED_FIXED_COHORT_DIAGNOSTIC',cohort_records=len(meta),rth_symbols=len(needed),source_daily_ohlc_comparison=comparison,complete_dynamic_point_in_time_market=False,prefilter_exhaustiveness_certified=False,quote_execution_verified=False,commission_and_regulatory_fees_verified=False,sector_classifications_last_known_at='2025-04-25T20:19:02Z'))
    (output/'manifest.json').write_text(canonical(manifest)+'\n');(r/'scan-summary.json').write_text(json.dumps(dict(counts),indent=2)+'\n')
    print('normalized manifest ready',dict(counts),flush=True)


if __name__=='__main__':main()
