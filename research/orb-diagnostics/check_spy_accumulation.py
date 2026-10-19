"""Long SPY cash-flow comparison on sealed public daily data. No broker tools."""
import argparse
import csv
from datetime import date,datetime,timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from spy_accumulation import ARMS,simulate
from paper_intents import require


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(spy_path,cash_path,protocol):
    from dx27.adapters.calendars.xnys import load_xnys_calendar
    chart=json.loads(Path(spy_path).read_bytes())
    require(chart['chart']['error'] is None,'YAHOO_CHART_ERROR')
    result=chart['chart']['result'][0]
    require(result['meta']['symbol']=='SPY' and not result.get('events',{}).get('splits'),
            'SPY_NO_SPLIT_CONTRACT_REQUIRED')
    require(result['meta']['exchangeTimezoneName']=='America/New_York','EXPLICIT_EXCHANGE_TIMEZONE_REQUIRED')
    quote=result['indicators']['quote'][0];adj=result['indicators']['adjclose'][0]['adjclose']
    times=result['timestamp'];require(all(len(quote[n])==len(times) for n in ('open','close'))
                                  and len(adj)==len(times),'YAHOO_SERIES_LENGTH')
    rows=[dict(date=datetime.fromtimestamp(t,timezone.utc).astimezone(ZoneInfo('America/New_York')).date(),
               open=quote['open'][i],close=quote['close'][i],adjclose=adj[i]) for i,t in enumerate(times)]
    require(len({r['date'] for r in rows})==len(rows),'DUPLICATE_PRICE_DATE')
    calendar=load_xnys_calendar(date(1998,1,1),date(2025,12,31))
    require([r['date'].isoformat() for r in rows]==[s.session_id for s in calendar.sessions],
            'PRICE_DATES_MUST_MATCH_COMPLETE_CALENDAR')
    rates=[]
    with Path(cash_path).open(newline='') as f:
        reader=csv.DictReader(f);require(reader.fieldnames==['observation_date','DGS3MO'],'FRED_CSV_SCHEMA')
        for row in reader:
            if row['DGS3MO'] in ('','.'):continue
            rates.append((date.fromisoformat(row['observation_date']),float(row['DGS3MO'])/100))
    expected=protocol['source_sha256']
    require(sha(spy_path)==expected['spy'] and sha(cash_path)==expected['cash'],'SOURCE_SEAL_MISMATCH')
    return rows,rates,dict(calendar_version=calendar.calendar_version,price_rows=len(rows),
        dividend_events=len(result.get('events',{}).get('dividends',{})),split_events=0,rate_observations=len(rates),
        price_dates_complete=True,source_sha256=expected)


def main(spy_path,cash_path,output):
    protocol_path=Path('docs/research/spy-long-hold/protocol.json')
    protocol=json.loads(protocol_path.read_text())
    require(protocol['arms']==list(ARMS) and protocol['drawdown_threshold']==.05 and
            protocol['lookback_sessions']==252 and protocol['dca_initial_months']==12,'FIXED_COMPARISON_PROTOCOL')
    rows,rates,quality=prepare(spy_path,cash_path,protocol)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    cases={};windows=[]
    for cash_mode in ('ZERO','TREASURY_PROXY'):
        for bps in (0,5):
            key=f'{cash_mode}_{bps}bps';cases[key]={}
            for arm in ARMS:
                r=simulate(rows,start=date(2000,1,1),end=date(2025,12,31),arm=arm,
                           cash_mode=cash_mode,rates=rates,cost_bps=bps)
                ledger=r.pop('ledger')
                (output/f'{key}-{arm}-daily.json').write_text(json.dumps(ledger,indent=2)+'\n')
                cases[key][arm]=r
            require(len({r['total_contributed'] for r in cases[key].values()})==1,'CASH_FLOW_MISMATCH')
        for year in range(2000,2017):
            window=dict(start_year=year,end_year=year+9,cash_mode=cash_mode,results={})
            for arm in ARMS:
                r=simulate(rows,start=date(year,1,1),end=date(year+9,12,31),arm=arm,
                           cash_mode=cash_mode,rates=rates,cost_bps=0)
                r.pop('ledger');window['results'][arm]=r
            windows.append(window)
    summary={}
    for mode in ('ZERO','TREASURY_PROXY'):
        selected=[w for w in windows if w['cash_mode']==mode]
        summary[mode]=dict(overlapping_windows=len(selected),
            dip_beats_immediate=sum(w['results']['DIP5']['final_wealth']>w['results']['IMMEDIATE']['final_wealth'] for w in selected),
            dip_beats_dca=sum(w['results']['DIP5']['final_wealth']>w['results']['DCA12']['final_wealth'] for w in selected))
    report=dict(status='COMPLETE_EXPLORATORY_SPY_ACCUMULATION_COMPARISON',protocol_sha256=sha(protocol_path),
        engine_sha256=sha('research/orb-diagnostics/spy_accumulation.py'),runner_sha256=sha(__file__),
        data_quality=quality,main_period_cases=cases,ten_year_windows=windows,window_summary=summary,
        dividend_model='YAHOO_ADJUSTED_OHLC_TOTAL_RETURN_PROXY_NOT_EXACT_PAY_DATE_DRIP',
        cash_proxy='LAGGED_DGS3MO_YIELD_ACCRUAL_NOT_A_TRADED_BILL_RETURN_OR_ACCOUNT_RATE',
        taxes_modeled=False,independent_confirmation=False,paper_orders_submitted=0,
        daily_artifact_sha256={p.name:sha(p) for p in sorted(output.iterdir())})
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(main=cases,windows=summary),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spy',required=True);p.add_argument('--cash',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();main(a.spy,a.cash,a.output)
