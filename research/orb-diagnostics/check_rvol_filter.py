"""Complete exposed A/B replay of fixed R1 vs R1 + one RVOL filter. No broker."""
import argparse
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from fixed_artifacts import REPORTS
from rvol_filter import opening_rvol,replay_session
from paper_intents import require


def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(stage,csv_path,artifacts,output):
    from dx27.research.registration import stage_calendar
    from dx27.core.models.market_context import MarketContext
    from dx27.research.opening_direction import MINUTE
    root=Path('.');artifacts=Path(artifacts);output=Path(output)
    protocol=load('docs/research/orb-literature/rvol-exploration.json')
    require(protocol['lookback_sessions']==14 and protocol['minimum_rvol']==1
            and protocol['attempts']==['R1','R1_RVOL14_GE1'],'FIXED_SINGLE_FILTER_PROTOCOL_REQUIRED')
    public=root/f'docs/reports/orb-stage-{stage.lower()}'
    require(sha(public/'report.json')==REPORTS[stage],'ORIGINAL_REPORT_SEAL')
    original=load(public/'report.json')
    require(sha(csv_path)==original['input']['csv_sha256'],'ORIGINAL_CSV_SEAL')
    for f,h in original['source_files'].items():require(sha(f)==h,'FROZEN_SOURCE_CHANGED')
    manifest=load(public/'completion.json')['artifact_sha256']
    for f in ('R1-fills.json','R1-daily.json'):
        require(sha(artifacts/f)==manifest[f],'ORIGINAL_LEDGER_SEAL')
    design=load('docs/research/orb-literature/evaluation-design.json')
    calendar,context,sessions=stage_calendar(design,stage)
    require(calendar.calendar_version==original['calendar_version'],'ORIGINAL_CALENDAR_SEAL')
    slots={s.opens_at+i*MINUTE:(s.session_id,i) for s in context for i in range(int((s.closes_at-s.opens_at)/MINUTE))}
    rows={s.session_id:[None]*int((s.closes_at-s.opens_at)/MINUTE) for s in context}
    volumes={s.session_id:Decimal(0) for s in context}
    with Path(csv_path).open(newline='') as f:
        for row in csv.DictReader(f):
            if row['symbol']!='QQQ':continue
            at=datetime.fromisoformat(row['timestamp'])
            if at not in slots:continue
            day,i=slots[at];require(rows[day][i] is None,'DUPLICATE_REGULAR_MINUTE')
            rows[day][i]=MarketContext('QQQ',at,'1m',*(float(row[k]) for k in ('open','high','low','close','volume')))
            if i<5:volumes[day]+=Decimal(row['volume'])
    require(all(all(b is not None and b.volume>0 for b in bars) for bars in rows.values()),'INCOMPLETE_CONTEXT_OR_SESSION')
    history=[];rvol={}
    for s in context:
        if len(history)>=14:rvol[s.session_id]=opening_rvol(history,volumes[s.session_id])
        history.append(volumes[s.session_id])
    output.mkdir(parents=True,exist_ok=False)
    results={};old_daily=load(artifacts/'R1-daily.json');old_fills=load(artifacts/'R1-fills.json')
    for arm in protocol['attempts']:
        cash=100000.;peak=cash;mdd=0.;daily=[];fills=[];decisions=[];gated=0;gross=0.;fee=0.;spread=0.;slip=0.;turnover=0.
        for s in sessions:
            eligible=arm=='R1' or rvol[s.session_id]['eligible']
            r=replay_session(s,rows[s.session_id],cash,entry_eligible=eligible)
            cash=r['report']['cash'];gated+=r['gated_long'];daily.append(r['daily']);fills.extend(r['fills'])
            decisions.append(dict(session=s.session_id,**rvol[s.session_id],entry_eligible=eligible,
                gated_long=r['gated_long'],closed_trades=r['report']['closed_trades']))
            gross+=r['report']['gross_pnl'] or 0.;fee+=r['report']['commission']
            spread+=r['report']['spread_cost'];slip+=r['report']['slippage_cost']
            for f in r['fills']:turnover+=f['quantity']*f['reference']
            for e in r['equity']:
                peak=max(peak,e['equity']);mdd=max(mdd,1-e['equity']/peak)
        require(abs((cash-100000)-(gross-fee-spread-slip))<1e-6,'AGGREGATE_CASH_RECONCILIATION')
        if arm=='R1':
            require(len(fills)==len(old_fills) and len(daily)==len(old_daily),'BASELINE_COUNT_MISMATCH')
            for a,b in zip(fills,old_fills):require(a==b,'BASELINE_FILL_NOT_EXACT')
            for a,b in zip(daily,old_daily):
                require(all(a[k]==b[k] for k in a),'BASELINE_DAILY_NOT_EXACT')
        for name,data in [('daily',daily),('fills',fills),('decisions',decisions)]:
            (output/f'{arm}-{name}.json').write_text(json.dumps(data,indent=2)+'\n')
        results[arm]=dict(sessions=len(sessions),return_fraction=cash/100000-1,net_pnl=cash-100000,
            gross_pnl=gross,commission=fee,spread_cost=spread,slippage_cost=slip,
            trades=len(fills)//2,no_trade_days=sum(d['closed_trades']==0 for d in daily),
            gated_long_days=gated,minute_equity_max_drawdown=mdd,reference_turnover=turnover,
            gross_bps_of_turnover=gross/turnover*10000 if turnover else None,
            net_bps_of_turnover=(cash-100000)/turnover*10000 if turnover else None,
            fixed_fill_extra_bps={str(bps):(cash-100000)-bps*turnover/10000 for bps in [0,1,2,5]},
            months={month:sum(d['net_pnl'] for d in daily if d['session'].startswith(month))
                    for month in sorted({d['session'][:7] for d in daily})})
    report=dict(status='COMPLETE_EXPOSED_DATA_SINGLE_FILTER_EXPLORATION',stage=stage,
        original_r1_exact_fills_and_daily_match=True,protocol_sha256=sha('docs/research/orb-literature/rvol-exploration.json'),
        script_sha256=sha(__file__),filter_sha256=sha('research/orb-diagnostics/rvol_filter.py'),
        input_csv_sha256=original['input']['csv_sha256'],source_files_unchanged=len(original['source_files']),
        availability='ASSUMED_BAR_END_NOT_ORIGINAL_RECEIPT',costs='ORIGINAL_UNCALIBRATED_MODEL',
        own_capital_carried_per_arm=True,results=results,
        candidate_minus_baseline_net_pnl=results['R1_RVOL14_GE1']['net_pnl']-results['R1']['net_pnl'],
        effectiveness_established=False,independent_confirmation=False,paper_strategy_changed=False,
        artifact_sha256={p.name:sha(p) for p in sorted(output.iterdir())})
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=['A','B'],required=True);p.add_argument('--csv',required=True)
    p.add_argument('--artifacts',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(run(a.stage,a.csv,a.artifacts,a.output),indent=2))
