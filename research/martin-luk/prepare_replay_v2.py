"""Build sealed MLP2 sessions from frozen coverage and private raw caches."""
import argparse
from collections import defaultdict
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3

from capture_replay_v2 import required_symbols
from history_screen import normalize_rth, split_adjust
from strategy import canonical, ema


def normalized_actions(records, symbols):
    parent = {}
    def find(s):
        parent.setdefault(s,s)
        if parent[s] != s: parent[s] = find(parent[s])
        return parent[s]
    for a in records.get('name_changes',[]):
        parent[find(a['new_symbol'])] = find(a['old_symbol'])
    roots = defaultdict(list)
    for s in symbols: roots[find(s)].append(s)
    out, seen = [], set()
    for kind,rows in records.items():
        if kind == 'name_changes': continue
        for a in rows:
            sym = a.get('symbol') or a.get('source_symbol') or a.get('acquiree_symbol') or a.get('old_symbol')
            if not sym: continue
            for target in roots.get(find(sym),[]):
                key = (a['id'],target)
                if key in seen: continue
                seen.add(key)
                date = a.get('ex_date') or a.get('effective_date') or a.get('process_date')
                z = dict(id=a['id']+':'+target,symbol=target,date=date,kind=kind)
                if kind in ('forward_splits','reverse_splits'):
                    z.update(kind='split',ratio=a['new_rate']/a['old_rate'])
                elif kind == 'stock_dividends': z.update(kind='split',ratio=a['rate'])
                elif kind == 'cash_dividends':
                    if not a.get('payable_date') or a.get('rate') is None:
                        z.update(kind='UNRESOLVED_CASH_DIVIDEND')
                    else: z.update(kind='cash_dividend',rate=a['rate'],payable_date=a['payable_date'])
                out.append(z)
    return sorted(out,key=lambda a:(a['date'],0 if a['kind']=='split' else 1,a['id']))


def daily_exit_flags(day, prior, source, splits):
    flags = {}
    for symbol,history in source.items():
        rows = [history.get(s['date']) for s in prior]
        if len(rows) != 160 or any(b is None for b in rows): continue
        adjusted = split_adjust(rows,day,splits.get(symbol,[]))
        cs = [b['c'] for b in adjusted]
        if not all(type(c) in (int,float) and math.isfinite(c) and c>0 for c in cs): continue
        flags[symbol] = cs[-1] < ema(cs,9)[-1]
    return flags


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--coverage',type=Path,required=True)
    p.add_argument('--old-root',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    a = p.parse_args()
    symbols = required_symbols(a.coverage); symbols.pop('SPY')
    schedule = json.loads((a.old_root/'schedule.json').read_text())
    db = sqlite3.connect(a.root/'rth.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS bars(symbol TEXT,date TEXT,data BLOB,PRIMARY KEY(symbol,date))')
    db.execute('CREATE TABLE IF NOT EXISTS raw_sources(symbol TEXT PRIMARY KEY,sha256 TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS by_date ON bars(date)');db.commit()
    test_schedule = [s for s in schedule if '2025-04-28'<=s['date']<='2025-12-31']
    for symbol in sorted(set(symbols)|{'SPY'}):
        file = a.root/'five-minute'/(symbol+'.json.gz')
        raw = gzip.decompress(file.read_bytes());digest = sha256(raw).hexdigest()
        receipt = json.loads(file.with_name(symbol+'.receipt.json').read_text())
        if digest != receipt['normalized_raw_sha256']: raise ValueError('RAW_BAR_SEAL_MISMATCH')
        previous = db.execute('SELECT sha256 FROM raw_sources WHERE symbol=?',(symbol,)).fetchone()
        if previous and previous[0]==digest: continue
        days,_ = normalize_rth(json.loads(raw),test_schedule)
        db.execute('DELETE FROM bars WHERE symbol=?',(symbol,))
        for day,rows in days.items():
            if rows:
                db.execute('INSERT INTO bars VALUES(?,?,?)',(symbol,day,gzip.compress(canonical(rows).encode(),mtime=0)))
        db.execute('INSERT OR REPLACE INTO raw_sources VALUES(?,?)',(symbol,digest));db.commit()
        print('normalized',symbol,flush=True)
    splits = json.loads((a.old_root/'splits.json').read_text())
    source = {}
    for f in sorted((a.old_root/'daily').glob('*.gz')):
        for s,rows in json.loads(gzip.decompress(f.read_bytes())).items():
            if s in symbols: source[s] = {b['t'][:10]:b for b in rows}
    records = json.loads((a.old_root/'all-actions.json').read_text())
    actions = normalized_actions(records,symbols)
    coverage = json.loads((a.coverage/'summary.json').read_text())
    refs = {r['path'][:10]:r for r in coverage['sessions_manifest']}
    out = a.root/'normalized';out.mkdir(exist_ok=True)
    sessions = []
    for i,s in enumerate(schedule):
        d = s['date']
        if d not in refs: continue
        reference = refs[d]
        raw = gzip.decompress((a.coverage/reference['path']).read_bytes())
        if sha256(raw).hexdigest() != reference['sha256']: raise ValueError('COVERAGE_SEAL_MISMATCH')
        plan = json.loads(raw)['plans']['MLP2']
        bars = {symbol:json.loads(gzip.decompress(raw)) for symbol,raw in
            db.execute('SELECT symbol,data FROM bars WHERE date=?',(d,)) if symbol in symbols}
        payload = dict(date=d,plan=plan,bars=bars,
            daily_exit=daily_exit_flags(d,schedule[i-160:i],source,splits),
            actions=[x for x in actions if x['date']==d])
        raw = canonical(payload).encode();filename = d+'.json.gz'
        (out/filename).write_bytes(gzip.compress(raw,mtime=0))
        sessions.append(dict(path=filename,sha256=sha256(raw).hexdigest()))
    here = Path(__file__).parent
    files = ('strategy.py','strategy_v2.py','history_replay_v2.py','run_replay_v2.py','prepare_replay_v2.py')
    manifest = dict(initial_cash=100000,sessions=sessions,code_sha256={n:sha256((here/n).read_bytes()).hexdigest() for n in files},
        coverage_sha256=sha256((a.coverage/'summary.json').read_bytes()).hexdigest(),
        provenance=dict(universe='ARCHIVED_FIXED_COHORT_DIAGNOSTIC',dynamic_point_in_time_verified=False,
            first_source_availability_verified=False,independent_out_of_sample=False,quote_execution_verified=False))
    (out/'manifest.json').write_text(canonical(manifest)+'\n')
    print('prepared',len(sessions),'sessions',flush=True)


if __name__ == '__main__': main()
