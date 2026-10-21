"""Offline, sealed-response field/coverage audit. Does not compute returns.

Schema absence blocks a direct EPS-surprise backtest; schema presence alone
does not authenticate data, establish a historical vintage, or prove coverage.
"""
import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse


EXPECTED_URLS={
    'sec-submissions':'https://data.sec.gov/submissions/CIK0001045810.json',
    'sec-eps':'https://data.sec.gov/api/xbrl/companyconcept/CIK0001045810/us-gaap/EarningsPerShareDiluted.json',
    'alphavantage-ibm-demo':'https://www.alphavantage.co/query?function=EARNINGS&symbol=IBM&apikey=demo',
    'alpaca-doc-index':'https://docs.alpaca.markets/us/llms.txt',
}


def instant(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.utcoffset() is None:raise ValueError('TIMEZONE_REQUIRED')
    return result


def sealed(root,name):
    root=Path(root);m=json.loads((root/(name+'.meta.json')).read_text())
    if m.get('id')!=name:raise ValueError('SOURCE_ID_MISMATCH')
    if name in EXPECTED_URLS and m.get('url')!=EXPECTED_URLS[name]:
        raise ValueError('REQUEST_BINDING_FAILED')
    if m.get('http_status')!=200:return m,None
    raw=(root/(name+'.raw')).read_bytes()
    if sha256(raw).hexdigest()!=m['sha256'] or len(raw)!=m['bytes']:
        raise ValueError('SOURCE_SEAL_FAILED')
    return m,raw


def news_inventory(root):
    items=[];proofs=[];token=None;seen=set();page=0
    while True:
        name='alpaca-news' if page==0 else f'alpaca-news-{page:03d}'
        m,raw=sealed(root,name);proofs.append(m)
        if raw is None:return dict(status='INCOMPLETE_ACCESS',records=len(items)),proofs
        request=parse_qs(urlparse(m['url']).query)
        expected={'symbols':['NVDA'],'start':['2025-05-28T00:00:00Z'],
            'end':['2025-05-30T00:00:00Z'],'limit':['50'],'sort':['asc'],'include_content':['true']}
        if token:expected['page_token']=[token]
        if (urlparse(m['url']).netloc!='data.alpaca.markets'
                or urlparse(m['url']).path!='/v1beta1/news' or request!=expected):
            raise ValueError('NEWS_REQUEST_BINDING_FAILED')
        b=json.loads(raw);items.extend(b['news']);token=b.get('next_page_token')
        if not token:break
        if token in seen:raise ValueError('REPEATED_PAGE_TOKEN')
        seen.add(token);page+=1
    if len({n['id'] for n in items})!=len(items):raise ValueError('DUPLICATE_NEWS_ID')
    keys=sorted(set().union(*(n.keys() for n in items))) if items else []
    return dict(status='COMPLETE_FOR_FIXED_SCHEMA_PILOT',pages=len(proofs),records=len(items),
        row_keys=keys,updated_after_creation=sum(instant(n['updated_at'])>instant(n['created_at']) for n in items),
        structured_actual_eps_field_present=any(k in keys for k in ('eps_actual','actual_eps','reportedEPS')),
        structured_consensus_field_present=any(k in keys for k in ('eps_estimate','estimated_eps','estimatedEPS')),
        historical_content_versions_verified=False,
        note='News text may mention EPS; extraction, accounting basis and pre-release consensus vintage are not established.'),proofs


def audit(root,old_events):
    root=Path(root);news,proofs=news_inventory(root)
    out=dict(alpaca_news=news)
    for name in ('sec-submissions','sec-eps','alphavantage-ibm-demo','alpaca-doc-index'):
        m,raw=sealed(root,name);proofs.append(m)
        if raw is None:
            out[name]=dict(status='ACCESS_NOT_ESTABLISHED');continue
        if name=='alpaca-doc-index':
            out[name]=dict(lines_matching_earnings=sum('earnings' in l.lower() for l in raw.decode().splitlines()),
                note='An index search is not proof that no provider product exists.');continue
        b=json.loads(raw)
        if name=='sec-submissions':
            out[name]=dict(filing_metadata_fields=sorted(b['filings']['recent']),
                announcement_time_verified=False,analyst_consensus_present=False)
        elif name=='sec-eps':
            rows=[x for rs in b['units'].values() for x in rs if x.get('end','')<='2025-12-31']
            periods=defaultdict(set)
            for unit,rs in b['units'].items():
                for x in rs:
                    if x.get('end','')<='2025-12-31':periods[(unit,x.get('start'),x['end'])].add(x['val'])
            out[name]=dict(fact_fields=sorted(set().union(*(x.keys() for x in rows))) if rows else [],
                historical_periods=len(periods),periods_with_multiple_values_across_filings=sum(len(v)>1 for v in periods.values()),
                period_end_cutoff='2025-12-31',
                records_filed_after_period_end_cutoff=sum(x.get('filed','')>'2025-12-31' for x in rows),
                analyst_consensus_present=False,
                note='Multiple values can reflect splits, differing disclosures or revisions; do not classify all as errors or choose the latest blindly.')
        else:
            rows=b.get('quarterlyEarnings',[])
            out[name]=dict(status='DEMO_SCHEMA_ONLY' if rows else 'DEMO_DATA_NOT_AVAILABLE',
                quarterly_rows=len(rows),reported_in_2025=sum(x.get('reportedDate','').startswith('2025') for x in rows),
                row_keys=sorted(set().union(*(x.keys() for x in rows))) if rows else [],
                pre_release_consensus_vintage_verified=False,eps_basis_verified=False,
                exact_release_timestamp_verified=False,broad_universe_access_verified=False)
    raw=Path(old_events).read_bytes();events=json.loads(raw)
    out['existing_blackout_events']=dict(records=len(events),sha256=sha256(raw).hexdigest(),
        unknown_release_times=sum(str(e.get('release_time','')).startswith('UNKNOWN') for e in events),
        actual_eps_records=sum('eps_actual' in e for e in events),
        consensus_eps_records=sum('eps_estimate' in e for e in events),
        note='Blackout dates are not EPS-surprise observations.')
    # Coverage/authentication is not established by this plumbing pilot.
    return dict(status='DATA_FEASIBILITY_NOT_ESTABLISHED',scope='SCHEMA_PILOT_NOT_REPRESENTATIVE_SAMPLE',
        providers=out,source_seals=proofs,qualified_event_universe_constructed=False,
        historical_pit_event_count=None,backtest_permitted=False,returns_computed=False,
        actual_orders=0,paid_access_purchased=False,source_authenticity_verified=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--old-events',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=audit(a.root,a.old_events);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2)+'\n')
    print(r['status'],'no event universe; no returns; no orders')
