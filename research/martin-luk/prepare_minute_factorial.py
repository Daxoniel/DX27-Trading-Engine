"""Build matched minute/5-minute factorial inputs; raw prices stay private."""
import argparse
from collections import defaultdict
from datetime import timedelta
import gzip
from hashlib import sha256
import json
from pathlib import Path

from strategy import canonical, stamp, validate_bars


def normalize(rows,opening):
    out=[];seen=set()
    for b in rows:
        start=stamp(b['t'])
        if not opening<=start<opening+timedelta(minutes=125):continue
        if (start-opening).total_seconds()%60 or start in seen:raise ValueError('DUPLICATE_OR_UNALIGNED_MINUTE')
        seen.add(start);end=start+timedelta(minutes=1)
        out.append(dict(start=start.isoformat(),end=end.isoformat(),available_at=(end+timedelta(seconds=1)).isoformat(),
            open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v']))
    return sorted(out,key=lambda b:b['start'])


def aggregate(rows,opening):
    groups=defaultdict(list)
    for b in rows:groups[int((stamp(b['start'])-opening).total_seconds()//300)].append(b)
    out=[]
    for key,bs in sorted(groups.items()):
        start=opening+timedelta(minutes=key*5);end=start+timedelta(minutes=5)
        invalid=False
        for b in bs:
            try:validate_bars([b],stamp(b['available_at']),1)
            except ValueError:invalid=True
        out.append(dict(start=start.isoformat(),end=end.isoformat(),available_at=(end+timedelta(seconds=1)).isoformat(),
            open=bs[0]['open'],high=max(b['high'] for b in bs),low=min(b['low'] for b in bs),
            close=bs[-1]['close'],volume=sum(b['volume'] for b in bs),invalid_components=invalid,
            observed_minutes=len(bs)))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    a=p.parse_args();out=a.root/'normalized';out.mkdir(exist_ok=True)
    base=json.loads(a.base.read_text());captured=json.loads((a.root/'minutes-manifest.json').read_text())
    if captured['base_manifest_sha256']!=sha256(a.base.read_bytes()).hexdigest():raise ValueError('BASE_MANIFEST_MISMATCH')
    refs={r['path'][:10]:r for r in captured['sessions']};sessions=[];comparison=defaultdict(int)
    for ref in base['sessions']:
        raw=gzip.decompress((a.base.parent/ref['path']).read_bytes())
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('BASE_INPUT_SEAL_MISMATCH')
        s=json.loads(raw);mref=refs[s['date']]
        raw=gzip.decompress((a.root/mref['path']).read_bytes())
        if sha256(raw).hexdigest()!=mref['sha256']:raise ValueError('MINUTE_INPUT_SEAL_MISMATCH')
        data=json.loads(raw)['bars'];opening=stamp(s['plan']['session_open']);cutoff=opening+timedelta(minutes=125)
        minutes={}
        for c in s['plan']['watchlist']:
            symbol=c['symbol'];rows=normalize(data.get(symbol,[]),opening);minutes[symbol]=rows
            derived=aggregate(rows,opening);old={b['start']:b for b in s['bars'].get(symbol,[])}
            for b in derived:
                if b['start'] not in old:comparison['new_opening_5m_intervals']+=1;continue
                comparison['compared_5m_intervals']+=1
                for key in ('open','high','low','close','volume'):
                    if b[key]!=old[b['start']][key]:comparison[key+'_different']+=1
            s['bars'][symbol]=derived+[b for b in s['bars'].get(symbol,[]) if stamp(b['start'])>=cutoff]
        s['minute_bars']=minutes
        raw=canonical(s).encode();filename=s['date']+'.json.gz'
        (out/filename).write_bytes(gzip.compress(raw,mtime=0));sessions.append(dict(path=filename,sha256=sha256(raw).hexdigest()))
    (out/'manifest.json').write_text(canonical(dict(sessions=sessions,initial_cash=100000,
        base_manifest_sha256=sha256(a.base.read_bytes()).hexdigest(),
        minutes_manifest_sha256=sha256((a.root/'minutes-manifest.json').read_bytes()).hexdigest(),
        opening_source_comparison=dict(comparison),provenance=base['provenance']))+'\n')
    print('prepared',len(sessions),'sessions',dict(comparison))


if __name__=='__main__':main()
