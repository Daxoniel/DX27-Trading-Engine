"""Fixed 6B-2I-1 read-only exploratory public capture; never a daily collector."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timezone
import hashlib
import json
from pathlib import Path
import urllib.request
from dx27.adapters.calendars.xnys import load_xnys_calendar

URLS={
 'fred_latest':'https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2&cosd=2005-01-01&coed=2026-10-06',
 'alfred_20260331':'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=BAMLH0A0HYM2&vintage_date=2026-03-31',
 'alfred_20261005':'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=BAMLH0A0HYM2&vintage_date=2026-10-05',
 'alfred_20261006':'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=BAMLH0A0HYM2&vintage_date=2026-10-06',
 'ice_methodology':'https://www.theice.com/publicdocs/data/Bond_Index_Methodologies.pdf',
 'ice_platform':'https://indices.ice.com/registration?AccessType=Full',
 'alfred_help':'https://alfred.stlouisfed.org/help',
 'fred_metadata':'https://fred.stlouisfed.org/series/BAMLH0A0HYM2',
 'alfred_download':'https://alfred.stlouisfed.org/series/downloaddata?seid=BAMLH0A0HYM2',
}


def capture_group(output,urls):
    output.mkdir(parents=True,exist_ok=False)
    def fetch(item):
        name,url=item
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(request,timeout=25) as response:
                raw=response.read();ctype=response.headers.get('Content-Type');status=response.status;final=response.url
            seen=datetime.now(timezone.utc).isoformat()
            (output/(name+'.payload')).write_bytes(raw)
            return {'capture_id':name,'url':url,'final_url':final,'http_status':status,'content_type':ctype,
                    'first_seen_at':seen,'bytes':len(raw),'payload_sha256':hashlib.sha256(raw).hexdigest()}
        except Exception as error:return {'capture_id':name,'url':url,'error':type(error).__name__+': '+str(error)}
    with ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(fetch,urls.items()))
    (output/'manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    return records


def run(output):
    if output.exists():raise ValueError('new immutable capture directory required')
    calendar=load_xnys_calendar(date(2026,1,1),date(2026,12,31))
    daily={s.session_id:'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=BAMLH0A0HYM2&vintage_date='+s.session_id for s in calendar.sessions if '2026-09-15'<=s.session_id<='2026-10-06'}
    records=capture_group(output/'captures',URLS)
    sample=capture_group(output/'daily-vintages',daily)
    return {'metadata_and_export_captures':len(records),'nominal_vintage_samples':len(sample),'admission_result':'NOT_ASSESSED_BY_CONNECTIVITY'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    print(json.dumps(run(p.parse_args().output_dir),sort_keys=True))
