from dataclasses import fields, replace
from pathlib import Path
from datetime import timedelta
import json
import numpy as np
import pytest

from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.research.composite_reference import ReferenceBuilder, CompositeReference
from dx27.intelligence.sentinel.research.reference_fixture import reference_fixture
from dx27.intelligence.sentinel.research.reference_library import validate_reference_library
from dx27.intelligence.sentinel.sensor_contracts import VintageMode

ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture(scope='module')
def tape():
    p=json.loads((ROOT/'research/sentinel/6b-2g-contracts/protocol.json').read_text())
    cal,builder,points=reference_fixture(p)
    states=tuple(builder.build(s.session_id,points) for s in cal.sessions[20:170])
    return p,cal,builder,points,states


def test_independent_formula_and_contributions(tape):
    _,cal,_,_,states=tape
    s,d=ReferenceBuilder(cal).build(states[-1],states[:-1])
    ps={name:np.asarray([x.measurement(name).value for x in states[:-1]]) for name in ['spy_return_20','rsp_return_20','spy_rv_20','vix_level','hy_oas_level']}
    ranks={name:float(np.mean(values<states[-1].measurement(name).value)+.5*np.mean(values==states[-1].measurement(name).value)) for name,values in ps.items()}
    expected=100/3*((2-ranks['spy_return_20']-ranks['rsp_return_20'])/2+(ranks['spy_rv_20']+ranks['vix_level'])/2+ranks['hy_oas_level'])
    assert s.value==pytest.approx(expected,abs=1e-10)
    z=[]
    for name in ('rsp_spy_relative_20','qqq_spy_relative_20'):
        values=np.asarray([x.measurement(name).value for x in states[:-1]])
        signed=(states[-1].measurement(name).value-np.median(values))/(1.4826*np.median(abs(values-np.median(values))))
        z.append(abs(signed))
        term=next(t for t in d.group_contributions if t.name==name)
        assert term.signed_components[0][1]==pytest.approx(signed)
    assert d.value==pytest.approx(max(z))
    assert s.delta is not None and d.delta is not None
    assert sum(t.value for t in s.group_contributions)==pytest.approx(s.value)


def test_future_order_duplicate_prefix_invariance(tape):
    _,cal,_,_,states=tape
    builder=ReferenceBuilder(cal)
    assert builder.build(states[-3],states)==builder.build(states[-3],tuple(reversed(states))+states)


def test_insufficient_history_and_no_skip_delta(tape):
    _,cal,_,_,states=tape
    builder=ReferenceBuilder(cal)
    assert all(x.data_status is DataStatus.INSUFFICIENT_HISTORY and x.value is None for x in builder.build(states[125],states[:125]))
    assert all(x.delta is None for x in builder.build(states[-1],states[:-2]))


def test_delayed_credit_unavailable_without_reweight(tape):
    _,cal,statebuilder,points,states=tape
    current=states[-1]
    day=current.snapshot.session_id
    delayed=tuple(replace(p,first_seen_at=p.first_seen_at+timedelta(days=2)) if p.source_record_id==day and p.subject_ref.subject_id=='fixture:hy_oas' else p for p in points)
    state=statebuilder.build(day,delayed)
    s,d=ReferenceBuilder(cal).build(state,states[:-1])
    assert s.data_status is DataStatus.STALE and s.value is None and s.group_contributions==()
    assert s.coverage.usable==4
    assert d.data_status is DataStatus.AVAILABLE


def test_zero_mad_is_insufficient(tape):
    _,cal,statebuilder,_,_=tape
    from dx27.intelligence.sentinel.research.state_fixture import synthetic_state_fixture
    p=tape[0]
    _,cal,_,points,builder,_,_=synthetic_state_fixture(p,150)
    states=tuple(builder.build(s.session_id,points) for s in cal.sessions[20:150])
    # Exact same valid measurement values, preserving immutable recorded cutoff.
    modified=[]
    for state in states:
        measurements=tuple(replace(m,value=0.) if m.sensor_id in ('rsp_spy_relative_20','qqq_spy_relative_20') else m for m in state.measurements)
        from dx27.intelligence.sentinel.research.reference_scenarios import replace_measurements
        modified.append(replace_measurements(state,measurements))
    assert ReferenceBuilder(cal).build(modified[-1],tuple(modified[:-1]))[1].data_status is DataStatus.INSUFFICIENT_HISTORY


def test_reject_descriptive_and_conflicting_history(tape):
    _,cal,_,_,states=tape
    current=replace(states[-1],snapshot=replace(states[-1].snapshot,vintage_mode=VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY))
    with pytest.raises(ValueError,match='vintage'):
        ReferenceBuilder(cal).build(current,states[:-1])
    with pytest.raises(TypeError):ReferenceBuilder(cal).build(states[-1],list(states[:-1]))


def test_reference_contract_and_library(tape,tmp_path):
    p,*_=tape
    assert set(f.name for f in fields(CompositeReference))==set(p['contracts']['CompositeReference']['fields'])
    report=validate_reference_library(ROOT/'research/sentinel/references',p)
    assert report['feeds']==19 and report['sensors']==18
    library=json.loads((ROOT/'research/sentinel/references/library.json').read_text())
    links=json.loads((ROOT/'research/sentinel/references/sensor_links.json').read_text())
    links['sensors'][0]['reference_ids'].append('REF-NOT-EXIST')
    (tmp_path/'library.json').write_text(json.dumps(library));(tmp_path/'sensor_links.json').write_text(json.dumps(links))
    with pytest.raises(ValueError,match='unresolved'):validate_reference_library(tmp_path,p)


def test_lagged_original_history_excluded_and_conflicts_rejected(tape):
    _,cal,_,_,states=tape
    from dx27.intelligence.sentinel.research.reference_scenarios import replace_measurements
    old=states[30]
    lagged=replace_measurements(old,tuple(replace(m,qualifiers=m.qualifiers+('LAGGED_INPUT',)) if m.sensor_id=='hy_oas_level' else m for m in old.measurements))
    history=states[:30]+(lagged,)+states[31:126]
    s,_=ReferenceBuilder(cal).build(states[126],history)
    assert s.data_status is DataStatus.INSUFFICIENT_HISTORY
    assert dict(s.coverage.prior_usable)['hy_oas_level']==125
    with pytest.raises(ValueError,match='conflicting'):
        ReferenceBuilder(cal).build(states[-1],states[:-1]+(lagged,))


def test_descriptor_reference_resolution(tape):
    p,_,_,_,states=tape
    from dx27.intelligence.sentinel.research.reference_library import references_for_sensor
    descriptor=next(d for d in states[-1].descriptors if d.sensor_id=='vix_level')
    resolved=references_for_sensor(ROOT/'research/sentinel/references',p,descriptor)
    assert 'REF-CBOE-VIX-METHODOLOGY' in resolved['reference_ids']
    assert resolved['descriptor_version']==descriptor.descriptor_version


def test_full_252_window_and_previous_delta_oldest_support():
    p=json.loads((ROOT/'research/sentinel/6b-2g-contracts/protocol.json').read_text())
    cal,builder,points=reference_fixture(p,276)
    # Once market-state formulas are independently checked, extend valid typed
    # recorded measurement evidence using shifted original session metadata.
    states=tuple(builder.build(s.session_id,points) for s in cal.sessions[20:276])
    refs=ReferenceBuilder(cal)
    current=refs.build(states[-1],states[:-1])
    previous=refs.build(states[-2],states[:-2])
    assert all(n==252 for _,n in current[0].coverage.prior_usable)
    for new,old in zip(current,previous):
        assert new.delta==pytest.approx(new.value-old.value)
    assert refs.build(states[-1],states[2:-1])==current
