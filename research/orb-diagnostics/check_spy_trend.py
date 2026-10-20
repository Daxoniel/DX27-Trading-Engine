"""Complete fixed monthly trend comparison using existing sealed SPY/FRED data."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

from check_spy_accumulation import prepare
from spy_trend import simulate_trend
from paper_intents import require


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(output):
    protocol_path=Path('docs/research/spy-trend/protocol.json')
    protocol=json.loads(protocol_path.read_text())
    require(protocol['sma_months']==10 and protocol['arms']==['HOLD','SMA10'] and
            protocol['signal_series']=='ADJUSTED_TOTAL_RETURN_CLOSE','FIXED_TREND_PROTOCOL_REQUIRED')
    old_protocol=json.loads(Path('docs/research/spy-long-hold/protocol.json').read_text())
    rows,rates,quality=prepare('work/spy-long-hold/spy-source.raw','work/spy-long-hold/cash-source.csv',old_protocol)
    require(quality['source_sha256']==protocol['source_sha256'],'UNCHANGED_SOURCE_REQUIRED')
    month_ends={r['date'] for i,r in enumerate(rows) if i==len(rows)-1 or
                 (r['date'].year,r['date'].month)!=(rows[i+1]['date'].year,rows[i+1]['date'].month)}
    # prepare verified every date against the complete fixed calendar; month ends
    # are known calendar dates, not selected using later market prices.
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    prior=json.loads(Path('docs/reports/spy-long-hold/report.json').read_text())
    cases={};windows=[]
    for mode in ('ZERO','TREASURY_PROXY'):
        for bps in (0,5):
            key=f'{mode}_{bps}bps';cases[key]={}
            for arm in ('HOLD','SMA10'):
                r=simulate_trend(rows,start=date(2000,1,1),end=date(2025,12,31),arm=arm,
                    cash_mode=mode,rates=rates,month_end_dates=month_ends,cost_bps=bps)
                ledger=r.pop('ledger');fills=r.pop('fills')
                for name,data in [('daily',ledger),('fills',fills)]:
                    (output/f'{key}-{arm}-{name}.json').write_text(json.dumps(data,indent=2)+'\n')
                if arm=='HOLD':
                    old=prior['main_period_cases'][key]['IMMEDIATE']
                    for field in ('final_wealth','total_contributed','money_weighted_annual_return',
                         'time_weighted_total_return','time_weighted_annual_return','unitized_close_max_drawdown',
                         'average_cash_weight','final_cash','modeled_cash_interest'):
                        require(r[field]==old[field],'ORIGINAL_HOLD_BASELINE_NOT_EXACT:'+field)
                cases[key][arm]=r
            require(cases[key]['HOLD']['total_contributed']==cases[key]['SMA10']['total_contributed'],
                    'IDENTICAL_CONTRIBUTIONS_REQUIRED')
        for year in range(2000,2017):
            w=dict(start_year=year,end_year=year+9,cash_mode=mode,results={})
            for arm in ('HOLD','SMA10'):
                r=simulate_trend(rows,start=date(year,1,1),end=date(year+9,12,31),arm=arm,
                    cash_mode=mode,rates=rates,month_end_dates=month_ends,cost_bps=0)
                r.pop('ledger');r.pop('fills');w['results'][arm]=r
                if arm=='HOLD':
                    old=next(x for x in prior['ten_year_windows'] if x['cash_mode']==mode and x['start_year']==year)['results']['IMMEDIATE']
                    require(r['final_wealth']==old['final_wealth'],'WINDOW_HOLD_NOT_EXACT')
            windows.append(w)
    window_summary={}
    for mode in ('ZERO','TREASURY_PROXY'):
        ws=[w for w in windows if w['cash_mode']==mode]
        window_summary[mode]=dict(windows=17,
            higher_final_wealth=sum(w['results']['SMA10']['final_wealth']>w['results']['HOLD']['final_wealth'] for w in ws),
            smaller_drawdown=sum(w['results']['SMA10']['unitized_close_max_drawdown']<w['results']['HOLD']['unitized_close_max_drawdown'] for w in ws),
            shorter_longest_underwater=sum(w['results']['SMA10']['recovery']['max_underwater_calendar_days']<
                w['results']['HOLD']['recovery']['max_underwater_calendar_days'] for w in ws))
    report=dict(status='COMPLETE_EXPLORATORY_FIXED_SMA10_COMPARISON',protocol_sha256=sha(protocol_path),
        engine_sha256=sha('research/orb-diagnostics/spy_trend.py'),runner_sha256=sha(__file__),
        data_quality=quality,original_all_four_hold_baselines_exact=True,all_34_window_hold_baselines_exact=True,
        main_period_cases=cases,ten_year_windows=windows,window_summary=window_summary,
        independent_confirmation=False,exact_faber_replication=False,actual_paper_orders=0,
        artifact_sha256={p.name:sha(p) for p in sorted(output.iterdir())})
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(main=cases,windows=window_summary),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    run(p.parse_args().output)
