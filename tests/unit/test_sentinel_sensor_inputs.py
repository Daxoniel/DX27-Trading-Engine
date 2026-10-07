from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone

import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow, Provenance, SubjectRef
from dx27.intelligence.sentinel.observations import ObservationEnvelope
from dx27.intelligence.sentinel.sensor_contracts import FeedBinding, SeriesPoint, VintageMode
from dx27.intelligence.sentinel.sensor_inputs import AvailabilityStamp, normalize_ohlcv_close, normalize_series_point
from dx27.intelligence.sentinel.universe import UniverseMembership, UniverseTier


@pytest.fixture(scope='module')
def calendar():
    return load_xnys_calendar(date(2026, 1, 1), date(2026, 12, 31))


def binding(feed='hy_oas', **kwargs):
    values = dict(feed_id=feed, subject_ref=SubjectRef('fixture:' + feed, 'series', symbol=feed.upper()),
                  source_id='fixture', source_version='1', raw_unit='percent', normalized_unit='basis_points',
                  validation_record_id='fixture-only:metadata-v1', validated_at=datetime(2025,1,1,tzinfo=timezone.utc),source_calendar_id='fixture:validated-source-daily')
    values.update(kwargs)
    return FeedBinding(**values)


def stamp(session, **kwargs):
    values = dict(published_at=session.closes_at+timedelta(minutes=10), first_seen_at=session.closes_at+timedelta(minutes=20),
                  source_record_id=session.session_id, revision_id='1', payload_sha256='a'*64)
    values.update(kwargs)
    return AvailabilityStamp(**values)


def window(session):
    return ObservationWindow(session.opens_at, session.closes_at, '1d')


def test_xnys_dst_early_close_holiday_and_bounds(calendar):
    assert calendar.get('2026-03-06').closes_at.hour == 21
    assert calendar.get('2026-03-09').closes_at.hour == 20
    assert calendar.get('2026-11-27').closes_at.hour == 18
    assert calendar.get('2026-11-27').decision_cutoff.hour == 20
    for day in ['2026-07-03','2026-11-26','2026-10-04','2027-01-04']:
        with pytest.raises(ValueError):
            calendar.get(day)
    assert calendar.age('2026-11-25','2026-11-27') == 1
    assert calendar.calendar_version == load_xnys_calendar(date(2026,1,1),date(2026,12,31)).calendar_version


def test_percent_to_basis_points_and_max_available_time(calendar):
    s=calendar.get('2026-10-06')
    st=stamp(s)
    p=normalize_series_point(binding(),window(s),DataStatus.AVAILABLE,3.2,st)
    assert p.value == 320
    assert p.available_at == st.first_seen_at
    p2=normalize_series_point(binding(),window(s),DataStatus.AVAILABLE,3.2,
                              replace(st,published_at=st.first_seen_at+timedelta(hours=1)))
    assert p2.available_at == p2.published_at
    unknown=replace(p,published_at=None)
    assert unknown.available_at == p.first_seen_at
    assert unknown.point_id != p.point_id
    assert unknown.lineage_id == p.lineage_id


@pytest.mark.parametrize('raw', [float('nan'),float('inf'),True,'3.2'])
def test_invalid_raw_values_become_source_error_without_zero(calendar,raw):
    s=calendar.get('2026-10-06')
    p=normalize_series_point(binding(),window(s),DataStatus.AVAILABLE,raw,stamp(s))
    assert p.data_status is DataStatus.SOURCE_ERROR and p.value is None


def test_input_contract_rejects_unknown_metadata_and_is_immutable(calendar):
    s=calendar.get('2026-10-06')
    p=normalize_series_point(binding(),window(s),DataStatus.AVAILABLE,3.2,stamp(s))
    with pytest.raises(FrozenInstanceError):
        p.value=0
    with pytest.raises(ValueError):
        replace(p,first_seen_at=datetime(2026,10,6))
    with pytest.raises(ValueError):
        replace(p,data_status=DataStatus.STALE)
    with pytest.raises(ValueError):
        replace(p,payload_sha256='oops')
    with pytest.raises(ValueError):
        binding(raw_unit='USD',normalized_unit='basis_points')
    with pytest.raises(ValueError):
        binding(validation_record_id='')
    assert set(f.name for f in fields(SeriesPoint)) == {
        'point_id','subject_ref','observation_window','data_status','value','unit','published_at','first_seen_at',
        'available_at','source_id','source_record_id','source_version','revision_id','payload_sha256','vintage_mode'}


def test_bridge_reuses_ohlcv_and_does_not_infer_publication_from_bar_time(calendar):
    s=calendar.get('2026-10-06')
    b=binding('spy',raw_unit='USD',normalized_unit='USD',price_basis='TOTAL_RETURN_AS_AVAILABLE',observation_label_policy='XNYS_SESSION',source_calendar_id='XNYS')
    st=stamp(s)
    provenance=(Provenance('fixture',s.closes_at,s.session_id,'1'),)
    membership=UniverseMembership(b.subject_ref.subject_id,UniverseTier.CORE,'fixture:universe','fixture:membership','test',provenance)
    ctx=MarketContext('SPY',s.closes_at,'1d',100,102,99,101,1000)
    e=ObservationEnvelope(b.subject_ref,window(s),DataStatus.AVAILABLE,provenance,membership,ctx)
    p=normalize_ohlcv_close(e,b,st,calendar,s.session_id)
    assert p.value == 101 and p.available_at == st.first_seen_at
    bad=replace(e,market_context=replace(ctx,high=100))
    assert normalize_ohlcv_close(bad,b,st,calendar,s.session_id).data_status is DataStatus.SOURCE_ERROR
    stale=replace(e,data_status=DataStatus.STALE)
    assert normalize_ohlcv_close(stale,b,st,calendar,s.session_id).value is None
    with pytest.raises(ValueError,match='provenance'):
        normalize_ohlcv_close(e,b,replace(st,source_record_id='other'),calendar,s.session_id)
    with pytest.raises(ValueError,match='window'):
        normalize_ohlcv_close(replace(e,observation_window=ObservationWindow(s.opens_at,s.closes_at-timedelta(hours=1),'1d')),
                              b,st,calendar,s.session_id)


def test_latest_vintage_is_an_explicit_point_tag(calendar):
    s=calendar.get('2026-10-06')
    p=normalize_series_point(binding(),window(s),DataStatus.AVAILABLE,3.2,
                              stamp(s,vintage_mode=VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY))
    assert p.vintage_mode is VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY


def test_ohlcv_timestamp_must_match_declared_label_policy_not_only_envelope(calendar):
    s=calendar.get('2026-10-06')
    b=binding('spy',raw_unit='USD',normalized_unit='USD',price_basis='TOTAL_RETURN_AS_AVAILABLE',
              observation_label_policy='XNYS_SESSION',source_calendar_id='XNYS')
    st=stamp(s);provenance=(Provenance('fixture',s.closes_at,s.session_id,'1'),)
    membership=UniverseMembership(b.subject_ref.subject_id,UniverseTier.CORE,'fixture:universe','fixture:membership','test',provenance)
    context=MarketContext('SPY',s.closes_at,'1d',100,102,99,101,1000)
    envelope=ObservationEnvelope(b.subject_ref,window(s),DataStatus.AVAILABLE,provenance,membership,context)
    for timestamp in [s.closes_at+timedelta(days=1),s.closes_at.replace(tzinfo=None)]:
        point=normalize_ohlcv_close(replace(envelope,market_context=replace(context,timestamp=timestamp)),b,st,calendar,s.session_id)
        assert point.data_status is DataStatus.SOURCE_ERROR and point.value is None
    date_label=datetime(2026,10,6,tzinfo=timezone.utc)
    labelled=replace(envelope,market_context=replace(context,timestamp=date_label))
    assert normalize_ohlcv_close(labelled,b,st,calendar,s.session_id).data_status is DataStatus.SOURCE_ERROR
    labelled_binding=replace(b,ohlcv_timestamp_policy='UTC_DATE_LABEL')
    assert normalize_ohlcv_close(labelled,labelled_binding,st,calendar,s.session_id).value==101
