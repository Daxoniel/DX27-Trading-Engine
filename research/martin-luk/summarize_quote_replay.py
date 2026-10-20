"""Publish aggregate quote-entry diagnostics after independent cash/quote audits."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from analyze_replay_v2 import monthly_nav, trade_statistics
from audit_quote_history import audit_quotes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--cohort',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    cohort={s['symbol']:s for s in json.loads(a.cohort.read_text())};runs={}
    for name in ('primary','observed-5bp','observed-10bp','observed-25bp'):
        folder=a.root/name
        read=lambda n:json.loads((folder/(n+'.json')).read_text())
        validation=audit_quotes(folder,a.root/'quote-pages')
        (folder/'independent-validation.json').write_text(json.dumps(validation,indent=2)+'\n')
        summary=read('summary');sources=summary.pop('quote_sources')
        fills,closed,events,nav=map(read,('fills','closed','events','nav'))
        stats=trade_statistics(closed,fills,cohort)
        buys=[f for f in fills if f['side']=='buy']
        wins=[t['pnl'] for t in closed if t['pnl']>0];losses=[-t['pnl'] for t in closed if t['pnl']<=0]
        mean_win=mean(wins) if wins else None;mean_loss=mean(losses) if losses else None
        runs[name]=dict(summary=summary,independent_accounting=validation,statistics=stats,
            entries=len(buys),partial_entries=sum(f['unfilled_cancelled']>0 for f in buys),
            mean_closed_winner=mean_win,mean_closed_loser=mean_loss,
            descriptive_break_even_win_fraction=mean_loss/(mean_win+mean_loss) if mean_win and mean_loss else None,
            entry_rejections=dict(Counter(e['reason'] for e in events if e['kind']=='QUOTE_ENTRY_REJECTED')),
            mean_observed_exposure_fraction=mean(n['gross']/n['equity'] for n in nav) if nav else None,
            monthly_nav=monthly_nav(nav),quote_responses_used=len(sources),
            private_artifact_sha256={n:sha256((folder/(n+'.json')).read_bytes()).hexdigest()
                for n in ('summary','fills','closed','events','nav','positions','receivables','scans')})
    sources=[]
    for f in sorted((a.root/'quote-pages').glob('*.meta.json')):
        m=json.loads(f.read_text())
        sources.append(dict(request_sha256=f.name.split('.')[0],sha256=m['sha256'],bytes=m['bytes']))
    (a.output/'quote-source-manifest.json').write_text(json.dumps(dict(records=sources),indent=2)+'\n')
    (a.output/'results-quote.json').write_text(json.dumps(dict(runs=runs,actual_orders=0,
        promotable=False,independent_out_of_sample=False,
        entry_quote_input_consistency_verified=True,exit_quote_execution_verified=False,
        note='Full shared-account reruns; original OHLC-proxy profitability is not accepted as executable evidence.'),indent=2)+'\n')


if __name__=='__main__':main()
