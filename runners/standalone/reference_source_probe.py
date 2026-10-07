"""Read-only 6B-2I source connectivity probe. Downloads are not historic vintages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import urllib.request

URLS={
    'vix':'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv',
    'hy_oas_graph':'https://fred.stlouisfed.org/graph/?id=BAMLH0A0HYM2',
    'hy_metadata':'https://fred.stlouisfed.org/series/BAMLH0A0HYM2',
    'ust_2y_metadata':'https://fred.stlouisfed.org/series/DGS2',
    'ust_10y_metadata':'https://fred.stlouisfed.org/series/DGS10',
    'vix_methodology':'https://cdn.cboe.com/api/global/us_indices/governance/VIX_Methodology.pdf',
}


def run(output,start,end):
    import yfinance as yf
    if output.exists() and any(output.iterdir()):
        raise ValueError('use a new capture directory; prior first-seen evidence is immutable')
    output.mkdir(parents=True,exist_ok=True)
    def capture(item):
        name,url=item
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(request,timeout=25) as response:
                raw=response.read();status=response.status;kind=response.headers.get('Content-Type')
            seen=datetime.now(timezone.utc).isoformat()
            (output/(name+'.payload')).write_bytes(raw)
            return {'feed':name,'url':url,'first_seen_at':seen,'http_status':status,'content_type':kind,
                    'bytes':len(raw),'payload_sha256':hashlib.sha256(raw).hexdigest(),
                    'historical_intraday_availability_verified':False}
        except Exception as error:
            return {'feed':name,'url':url,'capture_error':type(error).__name__+': '+str(error),
                    'historical_intraday_availability_verified':False}
    with ThreadPoolExecutor(max_workers=6) as pool: sources=list(pool.map(capture,URLS.items()))
    etfs=[]
    for ticker in ('SPY','RSP','QQQ','IWM'):
        try:
            frame=yf.Ticker(ticker).history(start=start,end=end,auto_adjust=True,actions=True)
            if frame.empty:raise ValueError('empty Yahoo series; no coverage claim')
            raw=frame.to_csv().encode();seen=datetime.now(timezone.utc).isoformat()
            (output/(ticker+'.csv')).write_bytes(raw)
            etfs.append({'feed':ticker.lower(),'provider':'Yahoo via yfinance '+yf.__version__,
                         'first_seen_at':seen,'rows':len(frame),'first_observation':str(frame.index.min()),
                         'last_observation':str(frame.index.max()),'payload_sha256':hashlib.sha256(raw).hexdigest(),
                         'vintage_mode':'LATEST_VINTAGE_DESCRIPTIVE_ONLY',
                         'historical_intraday_availability_verified':False,'source_binding_approved':False})
        except Exception as error:etfs.append({'feed':ticker.lower(),'capture_error':type(error).__name__+': '+str(error),'source_binding_approved':False})
    for name,records in [('capture_manifest.json',sources),('yahoo_capture_manifest.json',etfs)]:
        (output/name).write_text(json.dumps(records,indent=2)+'\n')
    return {'result':'CONNECTIVITY_PROBE_ONLY','source_admission':'BLOCKED_DATA',
            'successful_http_captures':sum('http_status' in r for r in sources),
            'etf_downloaded_rows':sum(r.get('rows',0) for r in etfs)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--start',required=True);parser.add_argument('--end',required=True)
    args=parser.parse_args();print(json.dumps(run(args.output_dir,args.start,args.end),sort_keys=True))
