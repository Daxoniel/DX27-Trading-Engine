"""HY OAS source audit only. Vintage dates never become intraday capture evidence."""
from __future__ import annotations
import csv
from datetime import date
import hashlib
import io
import json
import math
from pathlib import Path

SERIES='BAMLH0A0HYM2'


def parse_export(raw: bytes, vintage: str | None = None) -> dict:
    """Reject HTML, wrong series/vintage, duplicate dates, and invalid values."""
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    expected=SERIES if vintage is None else SERIES+'_'+date.fromisoformat(vintage).strftime('%Y%m%d')
    if reader.fieldnames!=['observation_date',expected]:
        raise ValueError('exact HY series/vintage CSV header required')
    observations={}
    for row in reader:
        day=date.fromisoformat(row['observation_date']).isoformat()
        if day in observations:raise ValueError('duplicate observation date')
        if vintage is not None and day>vintage:raise ValueError('future observation in nominal vintage')
        value=row[expected]
        if value in ('','.'):observations[day]=None;continue
        number=float(value)
        if not math.isfinite(number) or number<0:raise ValueError('finite nonnegative percent required')
        observations[day]=number
    if not observations:raise ValueError('empty series export')
    valid={d:v for d,v in observations.items() if v is not None}
    if not valid:raise ValueError('no usable observations')
    return {'observations':observations,'first_observation':min(valid),'last_observation':max(valid),
            'rows':len(observations),'usable_rows':len(valid),'missing_rows':len(observations)-len(valid),
            'raw_unit':'percent','normalized_unit':'basis_points','conversion_factor':100,
            'nominal_vintage':vintage,'intraday_availability_verified':False}


def verified_capture(directory: Path, record: dict) -> bytes:
    if record.get('http_status')!=200:raise ValueError('unsuccessful capture')
    path=directory/(record['capture_id']+'.payload')
    if path.parent.resolve()!=directory.resolve():raise ValueError('invalid capture filename')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=record['payload_sha256']:raise ValueError('capture hash mismatch')
    from datetime import datetime
    stamp=datetime.fromisoformat(record['first_seen_at'])
    if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError('aware actual first-seen required')
    return raw


def summarize_exports(capture_dir: Path, daily_dir: Path, calendar) -> dict:
    manifest=json.loads((capture_dir/'manifest.json').read_text())
    by_id={r['capture_id']:r for r in manifest}
    if len(by_id)!=len(manifest):raise ValueError('duplicate capture identity')
    exports=[];parsed={};failures=[]
    for name,vintage in [('fred_latest',None),('alfred_20260331','2026-03-31'),('alfred_20261005','2026-10-05'),('alfred_20261006','2026-10-06')]:
        try:
            result=parse_export(verified_capture(capture_dir,by_id[name]),vintage)
            parsed[name]=result
            exports.append({'capture_id':name,**{k:v for k,v in result.items() if k!='observations'},
                            'covers_requested_2005_start':result['first_observation']<='2005-01-01'})
        except (ValueError,KeyError,OSError) as error:failures.append({'capture_id':name,'error':str(error)})
    # Fixed recent completed-session grid, selected for exploratory source audit.
    expected=tuple(s for s in calendar.sessions if '2026-09-15'<=s.session_id<='2026-10-06')
    records=json.loads((daily_dir/'manifest.json').read_text());daily={r['capture_id']:r for r in records}
    if len(daily)!=len(records):raise ValueError('duplicate daily capture')
    rows=[];same=lag1=0;overlap_changes=overlap_compared=0;previous=None
    for session in expected:
        day=session.session_id
        try:
            result=parse_export(verified_capture(daily_dir,daily[day]),day)
            observed=result['last_observation']
            age=calendar.age_of_date(observed,day)
            same+=age==0;lag1+=age<=1
            rows.append({'nominal_vintage':day,'latest_observation':observed,'archive_date_proxy_age_XNYS':age,
                         'actual_first_seen_at':daily[day]['first_seen_at'],'original_cutoff_verified':False})
            if previous is not None:
                overlap=set(previous)&set(result['observations'])
                comparable=[d for d in overlap if previous[d] is not None and result['observations'][d] is not None]
                overlap_compared+=len(comparable)
                overlap_changes+=sum(previous[d]!=result['observations'][d] for d in comparable)
            previous=result['observations']
        except (ValueError,KeyError,OSError) as error:
            rows.append({'nominal_vintage':day,'error':str(error),'original_cutoff_verified':False})
    success=sum('latest_observation' in r for r in rows)
    return {'task_id':'6B-2I-1','audit_result':'SOURCE_AUDIT_COMPLETED','admission_result':'BLOCKED_DATA',
            'exports':exports,'export_failures':failures,'sample_role':'EXPLORATORY_NOMINAL_DATE_ARCHIVE_ONLY',
            'sample_start':'2026-09-15','sample_end':'2026-10-06','expected_sessions':len(expected),'usable_archive_samples':success,
            'archive_date_proxy_age0_count':same,'archive_date_proxy_age_le1_count':lag1,
            'archive_date_proxy_age0_fraction':same/len(expected) if success==len(expected) else None,
            'overlapping_usable_value_comparisons':overlap_compared,'observed_overlap_value_changes':overlap_changes,
            'revision_interpretation':'No observed overlap change does not establish immutable history or a complete revision audit.',
            'rows':rows,'calendar_version':calendar.calendar_version,'verified_original_cutoff_sessions':0,
            'actual_original_cutoff_coverage':None,'required_coverage_minimum':.95,'source_binding_approved':False,
            'nominal_dates_not_intraday_evidence':True,'operational_reference_enabled':False,'market_effectiveness_validated':False}
