"""Aggregate the frozen 2x2 experiment after independent raw-window audits."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean, median

from audit_minute_factorial import audit


CELLS=('5m-single','1m-single','5m-reentry','1m-reentry')


def describe(folder,manifest,quotes):
    read=lambda n:json.loads((folder/(n+'.json')).read_text())
    validation=audit(folder,manifest,quotes)
    (folder/'factorial-validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    s=read('summary');s.pop('quote_sources')
    fills,closed,events,nav,scans=(read(n) for n in ('fills','closed','events','nav','scans'))
    buys=[f for f in fills if f['side']=='buy'];by_id={f['trade_id']:f for f in buys}
    attempts=[e for e in events if e['kind']=='SIGNAL_ATTEMPT']
    entries_per_day=Counter(f['at'][:10] for f in buys);attempts_per_day=Counter(e['at'][:10] for e in attempts)
    groups=defaultdict(lambda:dict(trades=0,wins=0,pnl=0.))
    for t in closed:
        b=by_id[t['trade_id']];group='same_day_filled_reentry' if b['prior_fills_today'] else 'first_fill_of_day'
        groups[group]['trades']+=1;groups[group]['wins']+=t['pnl']>0;groups[group]['pnl']+=t['pnl']
    daily=[];previous=s['initial_cash']
    for scan in scans:
        daily.append(dict(date=scan['date'],equity=scan['equity'],return_since_previous_session=scan['equity']/previous-1))
        previous=scan['equity']
    cost=s['adverse_bps_each_side']/10000
    modeled_cost=sum(f['quantity']*(f['price']-f['reference_ask']) if f['side']=='buy'
        else f['quantity']*(f['price']/(1-cost)-f['price']) for f in fills)
    stops=[(f['price']-f['stop_price'])/f['price'] for f in buys]
    return dict(summary=s,independent_validation=validation,entries=len(buys),
        filled_same_day_reentries=sum(f['prior_fills_today']>0 for f in buys),
        first_fills_after_unfilled_attempts=sum(f['prior_fills_today']==0 and f['attempt_index']>1 for f in buys),
        repeat_signal_attempts=sum(e['attempt_index']>1 for e in attempts),
        attempt_prior_states=dict(Counter(e['prior_terminal_kind'] for e in attempts)),
        partial_entries=sum(f['unfilled_cancelled']>0 for f in buys),
        max_entries_per_day=max(entries_per_day.values(),default=0),
        max_signal_attempts_per_day=max(attempts_per_day.values(),default=0),
        median_actual_initial_stop_fraction=median(stops) if stops else None,
        mean_observed_exposure_fraction=mean(n['gross']/n['equity'] for n in nav) if nav else None,
        modeled_cost_for_realized_fill_path=modeled_cost,
        cost_note='Not a counterfactual cost-free return; higher-cost cells rerun eligibility and the full account.',
        worst_observed_session_return=min((d['return_since_previous_session'] for d in daily),default=None),
        closed_trade_groups=dict(groups),
        median_realized_r=median(t['realized_r'] for t in closed) if closed else None,
        final_exit_reasons=dict(Counter(f['reason'] for f in fills if f['side']=='sell' and f['reason']!='PARTIAL_3R')),
        entry_rejections=dict(Counter(e['reason'] for e in events if e['kind']=='QUOTE_ENTRY_REJECTED')),
        daily_equity=daily,private_artifact_sha256={n:sha256((folder/(n+'.json')).read_bytes()).hexdigest()
            for n in ('summary','fills','closed','events','nav','positions','receivables','scans')})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    runs={}
    for bps in (5,25):
        for cell in CELLS:
            name=cell+f'-{bps}bp';runs[name]=describe(a.root/name,a.manifest,a.root/'quote-pages')
            print('audited',name,flush=True)
    strict={cell:describe(a.root/(cell+'-strict'),a.manifest,a.root/'quote-pages') for cell in CELLS}
    contrasts={}
    for bps in (5,25):
        values={cell:runs[cell+f'-{bps}bp']['summary']['net_return'] for cell in CELLS}
        if any(v is None for v in values.values()):contrasts[str(bps)]=dict(status='INCOMPLETE_NO_FULL_PERIOD_COMPARISON');continue
        contrasts[str(bps)]=dict(status='RETROSPECTIVE_SIMULATED_DIFFERENCES',
            one_minute_effect_without_reentry_pp=100*(values['1m-single']-values['5m-single']),
            reentry_effect_at_five_minutes_pp=100*(values['5m-reentry']-values['5m-single']),
            reentry_effect_at_one_minute_pp=100*(values['1m-reentry']-values['1m-single']),
            joint_effect_vs_five_minute_single_pp=100*(values['1m-reentry']-values['5m-single']))
    sources=[]
    for f in sorted((a.root/'quote-pages').glob('*.meta.json')):
        m=json.loads(f.read_text());sources.append(dict(request_sha256=f.name.split('.')[0],sha256=m['sha256'],bytes=m['bytes']))
    parts=[];parts_dir=a.output/'quote-sources';parts_dir.mkdir(exist_ok=True)
    for i in range(0,len(sources),1000):
        name=f'quote-sources/{i//1000:04d}.json';raw=(json.dumps(sources[i:i+1000],indent=2)+'\n').encode()
        (a.output/name).write_bytes(raw);parts.append(dict(path=name,sha256=sha256(raw).hexdigest(),records=len(sources[i:i+1000])))
    (a.output/'quote-source-manifest.json').write_text(json.dumps(dict(records=len(sources),parts=parts,
        scope='Cache inventory includes prior reused responses; per-case audits bind actual buys to exact raw requests.'),indent=2)+'\n')
    result=dict(runs=runs,strict_completeness_checks=strict,contrasts=contrasts,actual_orders=0,promotable=False,
        independent_out_of_sample=False,matched_control_does_not_reproduce_prior_PR81_baseline=True,
        scope='One-minute execution clock and local fresh-bar policy shared by all cells; observed-only gaps and OHLC exits remain conditional.')
    (a.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
