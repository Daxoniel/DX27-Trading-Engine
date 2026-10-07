"""Independent formula checks and causal/adversarial state replay fixtures."""

from dataclasses import fields, replace
from datetime import timedelta
import json
from pathlib import Path
import random

import numpy as np
import pytest

from dx27.intelligence.sentinel.market_state import MarketStateBuilder, SensorRegistry, StateBuild
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow
from dx27.intelligence.sentinel.sensor_contracts import VintageMode

PROTOCOL = Path(__file__).resolve().parents[2] / 'research/sentinel/6b-2g-contracts/protocol.json'


@pytest.fixture(scope='module')
def fixture():
    from dx27.intelligence.sentinel.research.state_fixture import synthetic_state_fixture
    return synthetic_state_fixture(json.loads(PROTOCOL.read_text()))

def current(fixture,index=30):
    return fixture[1].sessions[index]


def build(fixture,points=None,index=30,bindings=None,mode=VintageMode.RECORDED_AS_AVAILABLE):
    registry,calendar,original,pts,_,_,_=fixture
    return MarketStateBuilder(registry,calendar,original if bindings is None else bindings,mode).build(
        current(fixture,index).session_id,pts if points is None else points)


def feed_points(points,feed):
    return tuple(p for p in points if p.subject_ref.subject_id=='fixture:'+feed)


def at(points,feed,day):
    return next(p for p in points if p.subject_ref.subject_id=='fixture:'+feed and p.source_record_id==day)


def test_independent_formulas_and_internal_divergence(fixture):
    state=build(fixture);rs=fixture[5]
    assert state.snapshot.data_status is DataStatus.AVAILABLE
    assert state.snapshot.coverage.registered.available==15
    assert state.snapshot.coverage.active_required.available==13
    assert state.snapshot.coverage.blocked.available==0
    assert state.snapshot.coverage.grade=='PARTIAL'
    expected_return=sum(rs['spy'][11:31])
    expected_rv=float(np.std(rs['spy'][11:31],ddof=1)*np.sqrt(252)*100)
    assert state.measurement('spy_return_20').value==pytest.approx(expected_return,abs=1e-10)
    assert state.measurement('rsp_return_20').value<0<state.measurement('spy_return_20').value
    assert state.measurement('rsp_spy_relative_20').value==pytest.approx(sum(rs['rsp'][11:31])-expected_return,abs=1e-10)
    assert state.measurement('qqq_spy_relative_20').value==pytest.approx(sum(rs['qqq'][11:31])-expected_return,abs=1e-10)
    assert state.measurement('spy_rv_20').value==pytest.approx(expected_rv,abs=1e-10)
    assert state.measurement('spy_rv_5_over_20').value==pytest.approx(np.std(rs['spy'][26:31],ddof=1)/np.std(rs['spy'][11:31],ddof=1),abs=1e-10)
    assert state.measurement('vix_minus_rv_20').value==pytest.approx(18-expected_rv,abs=1e-10)
    assert state.measurement('hy_oas_level').value==320
    assert state.measurement('ust_10y_minus_2y').value==150
    assert state.measurement('sofr_minus_effr').value==pytest.approx(10,abs=1e-10)
    participation=next(d for d in state.snapshot.dimensions if d.dimension_id=='participation')
    assert 'PROXY_ONLY' in participation.qualifiers and 'TRUE_BREADTH_UNAVAILABLE' in participation.qualifiers
    assert all(state.measurement(s).data_status is DataStatus.UNAVAILABLE for s in ['constituent_breadth_20','top7_weight','mega7_return_contribution_20'])
    vector=state.measurement('sector_relative_20').value
    assert len(vector)==9 and [x.subject_id for x in vector]==sorted(x.subject_id for x in vector)
    for value in vector:
        assert value.value==pytest.approx(sum(rs[value.subject_id.split(':')[1]][11:31])-expected_return,abs=1e-10)


def test_all_effective_point_refs_and_lineage_resolve(fixture):
    state=build(fixture)
    points={p.point_id:p for p in state.input_points}
    for m in state.measurements+state.sector_context:
        assert set(m.input_point_ids)<=points.keys()
        assert set(m.lineage_ids)=={points[i].lineage_id for i in m.input_point_ids}
        assert all(points[i].available_at<=state.snapshot.decision_cutoff for i in m.input_point_ids)
    spy=state.measurement('spy_rv_20');relative=state.measurement('qqq_spy_relative_20')
    assert set(spy.lineage_ids)<set(relative.lineage_ids)
    assert state.measurement('spy_return_20').lineage_ids==spy.lineage_ids


def test_input_order_duplicate_records_and_future_prefix_do_not_change_identity(fixture):
    points=fixture[3];s=current(fixture)
    prefix=tuple(p for p in points if p.available_at<=s.decision_cutoff)
    original=build(fixture,prefix)
    shuffled=list(points);random.Random(627).shuffle(shuffled)
    assert build(fixture,tuple(shuffled)).snapshot==original.snapshot
    assert build(fixture,points+prefix).snapshot==original.snapshot
    assert build(fixture,points).measurements==original.measurements


@pytest.mark.parametrize('clock',['published_at','first_seen_at'])
def test_not_yet_available_data_is_never_used(fixture,clock):
    day=current(fixture).session_id;p=at(fixture[3],'spy',day)
    modified=replace(p,**{clock:current(fixture).decision_cutoff+timedelta(seconds=1)})
    points=tuple(modified if x.point_id==p.point_id else x for x in fixture[3])
    state=build(fixture,points)
    assert state.measurement('spy_return_20').data_status is DataStatus.STALE
    assert state.measurement('spy_return_20').value is None
    assert modified.point_id not in {q.point_id for q in state.input_points}
    assert build(fixture,tuple(x for x in points if x.point_id!=modified.point_id)).snapshot==state.snapshot


def test_unseen_revision_is_ignored_then_applies_without_rewriting_prior_snapshot(fixture):
    session=current(fixture);p=at(fixture[3],'spy',fixture[1].sessions[25].session_id)
    revision=replace(p,value=p.value*1.05,revision_id='2',payload_sha256='b'*64,
                     published_at=session.decision_cutoff+timedelta(minutes=5),
                     first_seen_at=session.decision_cutoff+timedelta(minutes=10))
    old=build(fixture)
    future=build(fixture,fixture[3]+(revision,))
    assert future.snapshot==old.snapshot
    revised=build(fixture,fixture[3]+(revision,),index=31)
    baseline=build(fixture,index=31)
    assert revised.measurement('spy_rv_20').value!=baseline.measurement('spy_rv_20').value
    assert revision.point_id in revised.measurement('spy_rv_20').input_point_ids
    assert build(fixture,fixture[3]+(revision,)).snapshot==old.snapshot


def test_equal_time_ambiguous_revision_fails_and_numeric_sequence_is_explicit(fixture):
    day=current(fixture).session_id;p=at(fixture[3],'hy_oas',day)
    duplicate=replace(p,value=400,revision_id='2',payload_sha256='b'*64)
    state=build(fixture,fixture[3]+(duplicate,))
    assert state.measurement('hy_oas_level').data_status is DataStatus.SOURCE_ERROR
    assert 'AMBIGUOUS_REVISION' in state.measurement('hy_oas_level').qualifiers
    bindings=tuple(replace(b,revision_order='NUMERIC') if b.feed_id=='hy_oas' else b for b in fixture[2])
    state=build(fixture,fixture[3]+(duplicate,),bindings=bindings)
    assert state.measurement('hy_oas_level').value==400
    bad=replace(duplicate,revision_id='not-a-sequence')
    assert build(fixture,fixture[3]+(bad,),bindings=bindings).measurement('hy_oas_level').data_status is DataStatus.SOURCE_ERROR


def test_stale_gap_and_missing_sector_remain_partial_not_zero(fixture):
    day=current(fixture).session_id
    points=tuple(p for p in fixture[3] if not (p.source_record_id==day and p.subject_ref.subject_id=='fixture:xlb'))
    state=build(fixture,points)
    assert state.snapshot.data_status is DataStatus.AVAILABLE
    assert state.measurement('sector_relative_20').value is None
    assert state.measurement('sector_relative_20').data_status is DataStatus.STALE
    assert sum(m.data_status is DataStatus.AVAILABLE for m in state.sector_context)==8
    gap_day=fixture[1].sessions[20].session_id
    points=tuple(p for p in fixture[3] if not (p.source_record_id==gap_day and p.subject_ref.subject_id=='fixture:spy'))
    state=build(fixture,points)
    assert state.measurement('spy_return_20').value is None
    assert state.measurement('spy_return_20').data_status is DataStatus.STALE
    assert state.measurement('spy_return_20').reliability.usable_points==20


def test_lagged_levels_are_shown_but_misaligned_spreads_are_unavailable(fixture):
    day=current(fixture).session_id
    points=tuple(p for p in fixture[3] if not (p.source_record_id==day and p.subject_ref.subject_id in {'fixture:ust_2y','fixture:vix'}))
    state=build(fixture,points)
    assert state.measurement('ust_2y_level').data_status is DataStatus.AVAILABLE
    assert 'LAGGED_INPUT' in state.measurement('ust_2y_level').qualifiers
    assert state.measurement('ust_2y_level').observation_window.end<current(fixture).closes_at
    assert state.measurement('ust_10y_minus_2y').value is None
    assert state.measurement('vix_level').value==18
    assert state.measurement('vix_minus_rv_20').value is None
    points=tuple(p for p in points if p.source_record_id!=fixture[1].sessions[29].session_id or p.subject_ref.subject_id!='fixture:ust_2y')
    assert build(fixture,points).measurement('ust_2y_level').data_status is DataStatus.STALE


def test_latest_vintage_and_future_binding_do_not_certify_causal_state(fixture):
    points=tuple(replace(p,vintage_mode=VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY) for p in fixture[3])
    state=build(fixture,points)
    assert state.snapshot.data_status is DataStatus.UNAVAILABLE
    assert state.measurement('spy_return_20').value is None
    descriptive=build(fixture,points,mode=VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY)
    assert descriptive.snapshot.vintage_mode is VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY
    assert 'DESCRIPTIVE_ONLY' in descriptive.measurement('spy_return_20').qualifiers
    assert descriptive.snapshot.snapshot_id!=build(fixture).snapshot.snapshot_id
    bindings=tuple(replace(b,validated_at=current(fixture).decision_cutoff+timedelta(seconds=1)) for b in fixture[2])
    assert build(fixture,bindings=bindings).snapshot.data_status is DataStatus.UNAVAILABLE


def test_zero_variance_invalid_prices_and_short_history_are_explicit(fixture):
    points=tuple(replace(p,value=100) if p.subject_ref.subject_id=='fixture:spy' else p for p in fixture[3])
    state=build(fixture,points)
    assert state.measurement('spy_rv_20').value==0
    assert state.measurement('spy_rv_5_over_20').data_status is DataStatus.INSUFFICIENT_HISTORY
    day=current(fixture).session_id;p=at(fixture[3],'spy',day)
    invalid=tuple(replace(q,value=0) if q.point_id==p.point_id else q for q in fixture[3])
    assert build(fixture,invalid).measurement('spy_return_20').data_status is DataStatus.SOURCE_ERROR
    state=build(fixture,index=5)
    assert state.measurement('spy_return_20').data_status is DataStatus.INSUFFICIENT_HISTORY
    assert state.measurement('hy_oas_level').data_status is DataStatus.AVAILABLE


def test_only_frozen_config_and_causal_bindings_are_accepted(fixture):
    config=json.loads(PROTOCOL.read_text());config['availability']['fill_missing_sessions']=True
    with pytest.raises(ValueError,match='exact reviewed'):
        SensorRegistry.from_protocol(config)
    with pytest.raises(ValueError,match='price basis'):
        build(fixture,bindings=tuple(replace(b,price_basis='NOT_PRICE') if b.feed_id=='spy' else b for b in fixture[2]))
    state=build(fixture)
    with pytest.raises(ValueError,match='resolve'):
        replace(state,input_points=())
    contract=json.loads(PROTOCOL.read_text())['contracts']
    assert {f.name for f in fields(type(state.snapshot))}==set(contract['MarketStateSnapshot']['fields'])
    assert {f.name for f in fields(type(state.measurements[0]))}==set(contract['SensorMeasurement']['fields'])


def test_projection_preserves_peer_states_units_lag_and_empty_future_outputs(fixture):
    from dx27.intelligence.sentinel.state_projection import project_market_now
    original=build(fixture)
    report=project_market_now(original)
    now=report['market_now']
    assert report['report_schema_version']=='sentinel-report-multisensor-v0.2'
    assert now['status']=='DEGRADED'
    assert now['reference_values']==now['conditional_forecasts']==now['source_event_ids']==[]
    states={entry['sensor_id']:entry['state'] for entry in now['broad_equity']}
    assert states['spy_return_20']['value']['amount']>0>states['rsp_return_20']['value']['amount']
    assert states['spy_return_20']['value']['unit']=='log_return'
    breadth=next(e for e in now['participation'] if e['sensor_id']=='constituent_breadth_20')
    assert breadth['state']['value'] is None
    assert 'TRUE_BREADTH_UNAVAILABLE' in breadth['state']['qualifiers']
    assert now['state_snapshot_ref']['snapshot_id']==original.snapshot.snapshot_id
    assert now['coverage']['active_required']=={'expected':13,'available':13}
    day=current(fixture).session_id
    points=tuple(p for p in fixture[3] if not (p.source_record_id==day and p.subject_ref.subject_id=='fixture:xlb'))
    partial=project_market_now(build(fixture,points))['market_now']
    members=[e for e in partial['leadership'] if e['sensor_id']=='sector_relative_20']
    assert len(members)==9
    assert sum(e['state']['value'] is not None for e in members)==8
    assert all('PARTIAL_SECTOR_CONTEXT' in e['state']['qualifiers'] for e in members)
    serialized=json.dumps(report,allow_nan=False)
    assert 'RISK_ON' not in serialized and 'priority' not in serialized


def test_source_identity_metadata_changes_change_snapshot_and_never_fake_validation(fixture):
    points=fixture[3];p=at(points,'hy_oas',current(fixture).session_id)
    for field,value in [('source_id','unapproved_vendor'),('source_version','future-version'),('unit','percent')]:
        changed=tuple(replace(q,**{field:value}) if q.point_id==p.point_id else q for q in points)
        assert build(fixture,changed).measurement('hy_oas_level').data_status is DataStatus.SOURCE_ERROR
    bindings=tuple(replace(b,validation_record_id=b.validation_record_id+':revision') for b in fixture[2])
    assert build(fixture,bindings=bindings).snapshot.snapshot_id!=build(fixture).snapshot.snapshot_id
    with pytest.raises(ValueError,match='registry differs'):
        replace(fixture[0],feeds=(replace(fixture[0].feeds[0],max_age_sessions=10),)+fixture[0].feeds[1:])


def test_all_missing_inputs_and_optional_binding_gaps_are_explicit(fixture):
    state=build(fixture,points=(),bindings=())
    assert state.snapshot.data_status is DataStatus.UNAVAILABLE
    assert state.snapshot.coverage.grade=='UNAVAILABLE'
    assert all(m.value is None for m in state.measurements)
    core=tuple(b for b in fixture[2] if b.feed_id not in {'sofr','effr','xlb'})
    partial=build(fixture,bindings=core)
    assert partial.snapshot.data_status is DataStatus.AVAILABLE
    assert partial.measurement('sofr_minus_effr').value is None
    assert partial.measurement('sector_relative_20').value is None


def test_bad_observation_session_window_and_revision_fault_precedence(fixture):
    points=fixture[3];p=at(points,'hy_oas',current(fixture).session_id)
    changed=replace(p,observation_window=ObservationWindow(p.observation_window.start-timedelta(hours=12),p.observation_window.end,'1d'))
    state=build(fixture,tuple(changed if q.point_id==p.point_id else q for q in points))
    assert state.measurement('hy_oas_level').data_status is DataStatus.UNSUPPORTED_SESSION
    stale_day=fixture[1].sessions[28].session_id
    stale_error=replace(at(points,'hy_oas',stale_day),data_status=DataStatus.SOURCE_ERROR,value=None)
    removed=tuple(q for q in points if q.subject_ref.subject_id!='fixture:hy_oas' or q.source_record_id<stale_day)
    result=build(fixture,removed+(stale_error,)).measurement('hy_oas_level')
    assert result.data_status is DataStatus.SOURCE_ERROR
    assert 'STALE_INPUT' in result.qualifiers and 'SOURCE_SOURCE_ERROR' in result.qualifiers


def test_measurement_and_snapshot_contract_reject_mutable_or_incoherent_claims(fixture):
    state=build(fixture);m=state.measurement('spy_return_20')
    with pytest.raises(ValueError):
        replace(m,data_status=DataStatus.STALE)
    with pytest.raises(ValueError):
        replace(m,available_at=m.decision_cutoff+timedelta(seconds=1))
    with pytest.raises(TypeError):
        replace(m,input_point_ids=list(m.input_point_ids))
    with pytest.raises(ValueError):
        replace(m,reliability=replace(m.reliability,usable_points=22))
    vector=state.measurement('sector_relative_20')
    with pytest.raises(ValueError):
        replace(vector,value=1.0)
    with pytest.raises(ValueError):
        replace(vector,value=vector.value[:8])
    with pytest.raises(ValueError):
        replace(state.snapshot,coverage=replace(state.snapshot.coverage,grade='COMPLETE'))


def test_scalar_after_stock_close_is_eligible_and_same_date_spread_aligns(fixture):
    session=current(fixture);points=fixture[3];p=at(points,'vix',session.session_id)
    later=replace(p,observation_window=ObservationWindow(session.opens_at,session.closes_at+timedelta(minutes=15),'1d'))
    modified=tuple(later if q.point_id==p.point_id else q for q in points)
    state=build(fixture,modified)
    assert state.measurement('vix_level').value==18
    assert state.measurement('vix_minus_rv_20').data_status is DataStatus.AVAILABLE
    assert state.measurement('vix_minus_rv_20').observation_window.end==later.observation_window.end
    p=at(points,'ust_2y',session.session_id)
    earlier=replace(p,observation_window=ObservationWindow(session.opens_at,session.closes_at-timedelta(minutes=30),'1d'))
    state=build(fixture,tuple(earlier if q.point_id==p.point_id else q for q in points))
    assert state.measurement('ust_10y_minus_2y').value==150


def test_calendar_day_economic_period_keeps_its_original_date_and_lag(fixture):
    from datetime import datetime, timezone
    day=fixture[1].sessions[29].session_id;current_session=current(fixture)
    start=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    window=ObservationWindow(start,start+timedelta(days=1),'1d')
    points=tuple(p for p in fixture[3] if p.subject_ref.subject_id not in {'fixture:sofr','fixture:effr'})
    for feed in ['sofr','effr']:
        p=at(fixture[3],feed,day)
        points+=(replace(p,observation_window=window,published_at=current_session.opens_at,
                          first_seen_at=current_session.opens_at+timedelta(minutes=10)),)
    bindings=tuple(replace(b,observation_label_policy='UTC_DATE_BEFORE_EXCLUSIVE_END')
                   if b.feed_id in {'sofr','effr'} else b for b in fixture[2])
    state=build(fixture,points,bindings=bindings)
    funding=state.measurement('sofr_minus_effr')
    assert funding.value==pytest.approx(10,abs=1e-10)
    assert funding.observation_window==window
    assert 'LAGGED_INPUT' in funding.qualifiers
    bad=replace(points[-1],observation_window=ObservationWindow(start,start+timedelta(hours=23),'1d'))
    state=build(fixture,points[:-1]+(bad,),bindings=bindings)
    assert state.measurement('sofr_minus_effr').data_status is DataStatus.UNSUPPORTED_SESSION


def test_premature_capture_cannot_establish_a_completed_fact(fixture):
    session=current(fixture);p=at(fixture[3],'vix',session.session_id)
    bad=replace(p,published_at=session.closes_at-timedelta(minutes=10),first_seen_at=session.closes_at-timedelta(minutes=5))
    state=build(fixture,tuple(bad if q.point_id==p.point_id else q for q in fixture[3]))
    assert state.measurement('vix_level').data_status is DataStatus.SOURCE_ERROR
    assert state.measurement('vix_level').value is None


def test_cutoff_boundary_and_offset_timezone_representation_are_deterministic(fixture):
    from datetime import timezone
    p=at(fixture[3],'hy_oas',current(fixture).session_id)
    edge=replace(p,published_at=current(fixture).decision_cutoff,first_seen_at=current(fixture).decision_cutoff)
    points=tuple(edge if q.point_id==p.point_id else q for q in fixture[3])
    state=build(fixture,points)
    assert state.measurement('hy_oas_level').value==320
    equivalent=replace(edge,first_seen_at=edge.first_seen_at.astimezone(timezone(timedelta(hours=8))))
    assert equivalent.point_id==edge.point_id
    assert build(fixture,tuple(equivalent if q.point_id==edge.point_id else q for q in points)).snapshot==state.snapshot


def test_economic_source_can_report_on_an_xnys_holiday_without_fake_relabelling(fixture):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    p=at(fixture[3],'hy_oas',current(fixture).session_id)
    local=ZoneInfo('America/New_York')
    close=datetime(2026,4,3,16,tzinfo=local)  # Good Friday: XNYS closed, source calendar differs.
    point=replace(p,observation_window=ObservationWindow(close,close,'1d'),source_record_id='2026-04-03',
                  published_at=close+timedelta(minutes=10),first_seen_at=close+timedelta(minutes=20))
    state=fixture[4].build('2026-04-06',(point,))
    assert state.measurement('hy_oas_level').data_status is DataStatus.AVAILABLE
    assert 'SOURCE_NON_XNYS_DATE' in state.measurement('hy_oas_level').qualifiers
    assert 'LAGGED_INPUT' in state.measurement('hy_oas_level').qualifiers
    assert state.measurement('hy_oas_level').observation_window.end==point.observation_window.end
