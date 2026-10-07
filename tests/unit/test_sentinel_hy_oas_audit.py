import hashlib
from pathlib import Path
import pytest
from dx27.intelligence.sentinel.research.hy_oas_audit import parse_export,verified_capture


def test_vintage_header_missing_values_and_units():
    r=parse_export(b'observation_date,BAMLH0A0HYM2_20261005\n2026-10-02,3.1\n2026-10-03,.\n2026-10-05,3.2\n','2026-10-05')
    assert r['usable_rows']==2 and r['missing_rows']==1 and r['observations']['2026-10-03'] is None
    assert r['conversion_factor']==100 and not r['intraday_availability_verified']


@pytest.mark.parametrize('raw',[
 b'<html>updated today</html>',
 b'observation_date,BAMLH0A0HYM2\n2026-10-05,3.2\n',
 b'observation_date,BAMLH0A0HYM2_20261005\n2026-10-06,3.2\n',
 b'observation_date,BAMLH0A0HYM2_20261005\n2026-10-05,nan\n',
 b'observation_date,BAMLH0A0HYM2_20261005\n2026-10-05,3\n2026-10-05,4\n',
])
def test_reject_misidentified_future_invalid_or_duplicate_exports(raw):
    with pytest.raises(ValueError):parse_export(raw,'2026-10-05')


def test_capture_tamper_detection_and_real_time_awareness(tmp_path):
    raw=b'captured';(tmp_path/'one.payload').write_bytes(raw)
    record={'capture_id':'one','http_status':200,'payload_sha256':hashlib.sha256(raw).hexdigest(),'first_seen_at':'2026-10-07T12:00:00+00:00'}
    assert verified_capture(tmp_path,record)==raw
    (tmp_path/'one.payload').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='hash'):verified_capture(tmp_path,record)
    (tmp_path/'one.payload').write_bytes(raw);record['first_seen_at']='2026-10-07T12:00:00'
    with pytest.raises(ValueError,match='aware'):verified_capture(tmp_path,record)


def test_nominal_date_complete_coverage_never_qualifies_actual_cutoff(tmp_path):
    import json
    from datetime import date
    from dx27.adapters.calendars.xnys import load_xnys_calendar
    from dx27.intelligence.sentinel.research.hy_oas_audit import summarize_exports
    captures=tmp_path/'captures';daily=tmp_path/'daily';captures.mkdir();daily.mkdir()
    (captures/'manifest.json').write_text('[]')
    calendar=load_xnys_calendar(date(2026,1,1),date(2026,12,31))
    rows=[]
    for session in calendar.sessions:
        day=session.session_id
        if not '2026-09-15'<=day<='2026-10-06':continue
        raw=('observation_date,BAMLH0A0HYM2_'+day.replace('-','')+'\n'+day+',3.0\n').encode()
        (daily/(day+'.payload')).write_bytes(raw)
        rows.append({'capture_id':day,'http_status':200,'payload_sha256':hashlib.sha256(raw).hexdigest(),'first_seen_at':'2026-10-07T12:00:00+00:00'})
    (daily/'manifest.json').write_text(json.dumps(rows))
    report=summarize_exports(captures,daily,calendar)
    assert report['archive_date_proxy_age0_fraction']==1.0
    assert report['actual_original_cutoff_coverage'] is None
    assert report['verified_original_cutoff_sessions']==0 and report['admission_result']=='BLOCKED_DATA'
    (daily/'manifest.json').write_text(json.dumps(rows[:-1]))
    report=summarize_exports(captures,daily,calendar)
    assert report['archive_date_proxy_age0_fraction'] is None
    assert report['usable_archive_samples']==15 and report['rows'][-1]['original_cutoff_verified'] is False
