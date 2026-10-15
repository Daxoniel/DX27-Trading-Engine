"""Constructed minutes only: sequential equity, recovery and fixed statistics."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta, timezone
import json

import numpy as np
import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.core.models.market_context import MarketContext
from dx27.research.multisession import OpeningDirectionSequence
from dx27.research.opening_direction import OpeningDirectionFixture, MINUTE
from dx27.research.evaluation import evaluate_synthetic
from dx27.research.statistics import block_intervals, cost_sensitivity, comparison_report


@pytest.fixture
def sessions():
    return load_xnys_calendar(date(2025,3,10), date(2025,3,12)).sessions


def minute(session, i, *, close=100.5, **changes):
    values=dict(symbol="QQQ", timestamp=session.opens_at+i*MINUTE, timeframe="1m",
                open=100., high=101., low=99.5, close=close, volume=1_000_000.)
    values.update(changes)
    return MarketContext(**values)


def day(model, session, *, bearish=False, missing=None, gap=False):
    for i in range(int((session.closes_at-session.opens_at)/MINUTE)):
        if i==missing:
            model.on_closed_minute(model.next_at,None,as_of=model.next_at+MINUTE)
        else:
            close = 99.8 if bearish and i<5 else 100.5
            b=minute(session,i,close=close, **({"low":99.7,"high":100.8} if i>=5 else {}))
            if i>=7:b=replace(b,open=100.5)
            if gap and i==6:b=replace(b,open=10000.,high=10001.,low=9999.,close=10000.)
            model.on_closed_minute(b.timestamp,b,as_of=b.timestamp+MINUTE)


def test_capital_carries_and_zero_trade_day_does_not_reset(sessions):
    m=OpeningDirectionSequence(sessions,"R1")
    day(m,sessions[0]);first=m.daily[0]["ending_equity"]
    assert first>100000
    assert m._current.initial_cash==first
    day(m,sessions[1],bearish=True)
    assert m.daily[1]["starting_equity"]==m.daily[1]["ending_equity"]==first
    day(m,sessions[2])
    r=m.result()
    assert r.summary["status"]=="COMPLETE_RESEARCH_SEQUENCE"
    assert r.summary["performance_admissible"] is False
    assert r.daily[2]["starting_equity"]==first
    assert r.summary["ending_cash"]==pytest.approx(100000+sum(f["cash_delta"] for f in r.fills))
    assert np.prod([1+d["daily_return"] for d in r.daily])-1==pytest.approx(r.summary["net_pnl"]/100000)
    assert r.daily[1]["closed_trades"]==0


def test_checkpoint_across_completed_and_partial_days_restores_without_duplicates(sessions):
    a=OpeningDirectionSequence(sessions,"R1");day(a,sessions[0])
    for i in range(12):
        b=minute(sessions[1],i);a.on_closed_minute(b.timestamp,b,as_of=b.timestamp+MINUTE)
    cp=json.loads(json.dumps(a.checkpoint()))
    b=OpeningDirectionSequence.restore(cp,sessions=sessions,profile="R1")
    assert a.result()==b.result()
    for s in sessions[1:]:
        first=12 if s==sessions[1] else 0
        for i in range(first,int((s.closes_at-s.opens_at)/MINUTE)):
            bar=minute(s,i)
            for m in (a,b):m.on_closed_minute(bar.timestamp,bar,as_of=bar.timestamp+MINUTE)
    assert a.result()==b.result()
    assert len(a.result().trades)==len(sessions)
    with pytest.raises(ValueError):b.on_closed_minute(bar.timestamp,bar,as_of=bar.timestamp+MINUTE)
    cp["journals"][1]["starting_cash"]+=1
    with pytest.raises(ValueError,match="mismatch"):
        OpeningDirectionSequence.restore(cp,sessions=sessions,profile="R1")


def test_missing_day_blocks_later_days_and_cannot_drop_or_restart_capital(sessions):
    m=OpeningDirectionSequence(sessions,"R1");day(m,sessions[0],missing=8)
    assert m.next_at is None and m.blocked=="INCOMPLETE_SESSION"
    assert m.result().summary["net_pnl"] is None
    with pytest.raises(ValueError):day(m,sessions[1])
    restored=OpeningDirectionSequence.restore(m.checkpoint(),sessions=sessions,profile="R1")
    assert restored.blocked==m.blocked


def test_bankruptcy_is_recorded_without_recapitalization(sessions):
    m=OpeningDirectionSequence(sessions,"R0");day(m,sessions[0],bearish=True,gap=True)
    assert m.blocked=="NONPOSITIVE_CAPITAL"
    assert m.result().summary["ending_equity"]<0
    assert m.next_at is None


@pytest.mark.parametrize("cash",[0,-1,float('nan'),float('inf'),True,"100"])
def test_starting_cash_must_be_positive_finite_number(sessions,cash):
    with pytest.raises(ValueError):OpeningDirectionFixture(sessions[0],"R1",starting_cash=cash)


def test_offset_timestamps_normalize_checkpoint_and_restore(sessions):
    m=OpeningDirectionFixture(sessions[0],"R0",starting_cash=12345.)
    offset=timezone(timedelta(hours=2))
    for i in range(7):
        b=minute(sessions[0],i);b=replace(b,timestamp=b.timestamp.astimezone(offset))
        m.on_closed_minute(b.timestamp,b,as_of=b.timestamp+MINUTE)
    n=OpeningDirectionFixture.restore(m.checkpoint(),session=sessions[0],profile="R0",starting_cash=12345.)
    assert m.equity==n.equity and m.decisions==n.decisions and m.fills==n.fills


def test_calendar_checkpoint_and_session_order_are_pinned(sessions):
    with pytest.raises(ValueError):OpeningDirectionSequence(sessions[::-1],"R1")
    with pytest.raises(ValueError):OpeningDirectionSequence([sessions[0],sessions[0]],"R1")
    m=OpeningDirectionSequence(sessions,"R1");cp=m.checkpoint()
    cp['journals'].append(deepcopy(cp['journals'][0]))
    with pytest.raises(ValueError):OpeningDirectionSequence.restore(cp,sessions=sessions,profile='R1')


def test_block_bootstrap_constant_paths_and_pairing():
    x=block_intervals([.01]*4,[0.]*4,block_sessions=5,resamples=100)
    expected=1.01**4-1
    assert x['R1_net_return']==pytest.approx([expected,expected])
    assert x['R1_minus_baseline_pp']==pytest.approx([100*expected]*2)
    assert block_intervals([0,.01,-.02],[0,.01,-.02],block_sessions=2)['R1_minus_baseline_pp']==[0,0]
    assert x==block_intervals([.01]*4,[0.]*4,block_sessions=5,resamples=100)


@pytest.mark.parametrize('changes',[{'block_sessions':True},{'resamples':0},{'seed':-1}])
def test_bad_bootstrap_controls_rejected(changes):
    args=dict(block_sessions=5);args.update(changes)
    with pytest.raises(ValueError):block_intervals([0],[0],**args)


@pytest.mark.parametrize('returns',[[float('nan')],[-1],[float('inf')]])
def test_invalid_daily_returns_block_intervals(returns):
    with pytest.raises(ValueError):block_intervals(returns,[0],block_sessions=5)


def test_cost_scenarios_break_even_and_zero_turnover():
    fills=[dict(quantity=10,reference=100.),dict(quantity=10,reference=110.)]
    r=cost_sensitivity(21.,fills)
    assert r['reference_turnover']==2100
    assert r['break_even_extra_bps']==100
    assert [c['extra_cost'] for c in r['cases']]==pytest.approx([0,.21,.42,1.05])
    assert cost_sensitivity(-21.,fills)['break_even_extra_bps']==-100
    assert cost_sensitivity(0,[])['break_even_extra_bps'] is None


@pytest.fixture
def synthetic(tmp_path):
    p=tmp_path/'demo.csv';create_demo(p);return load_csv(p)


def test_synthetic_three_profile_pipeline_reconciles_and_keeps_zero_days(synthetic):
    report,results=evaluate_synthetic(synthetic)
    assert report['status']=='COMPLETE_SYNTHETIC_EVALUATION'
    assert report['effectiveness']=='NOT_EVALUATED' and not report['evaluation_registered']
    assert not report['execution_enabled']
    assert set(report['arms'])=={'R0','R1','baseline'}
    assert set(report['intervals_by_block_sessions'])=={'5','20'}
    for key,r in results.items():
        assert report['arms'][key]['net_pnl']==pytest.approx(r.summary['ending_cash']-r.summary.get('initial_cash',100000))
    assert len(report['paired_daily'])==len(results['R1'].daily)


def test_synthetic_entry_refuses_real_tag_before_calculation(synthetic):
    with pytest.raises(ValueError,match='SYNTHETIC'):
        evaluate_synthetic(IntradayDataset(synthetic.bars,dict(synthetic.provenance,source='ALPACA_HISTORICAL_SIP')))


def test_warmup_does_not_trade_or_enter_evaluation_returns(synthetic):
    _,all_results=evaluate_synthetic(synthetic)
    start=all_results['R1'].daily[-1]['session']
    report,results=evaluate_synthetic(synthetic,decision_start=start)
    assert len(report['paired_daily'])==1
    assert all(len(r.daily)==1 for r in results.values())


@pytest.mark.parametrize('corruption',['daily','cash','minute','fill','missing_minute','quality'])
def test_report_fails_closed_on_accounting_or_coverage_corruption(synthetic,corruption):
    _,results=evaluate_synthetic(synthetic)
    r=results['R1'];sessions=load_xnys_calendar(date(2025,11,26),date(2025,11,28)).sessions
    if corruption=='daily':r.daily[0]['starting_equity']+=1
    if corruption=='cash':r.summary['ending_cash']+=1
    if corruption=='minute':r.equity[0]['holdings_value']+=1
    if corruption=='fill':r.fills[0]['cash_delta']+=1
    if corruption=='missing_minute':r.equity.pop()
    if corruption=='quality':r.quality.append({'reason':'missing'})
    with pytest.raises(ValueError):comparison_report(results,sessions)


def test_local_artifacts_have_hashes_and_completion_last(synthetic,tmp_path):
    from dx27.research.evaluation import write_local_artifacts
    import hashlib
    report,results=evaluate_synthetic(synthetic)
    output=write_local_artifacts(report,results,tmp_path/'output')
    seal=json.loads((output/'completion.json').read_text(encoding="utf-8"))
    assert len(seal['artifact_sha256'])==22
    assert seal['study_status']=='COMPLETE_SYNTHETIC_EVALUATION'
    for path,sha in seal['artifact_sha256'].items():
        assert hashlib.sha256((output/path).read_bytes()).hexdigest()==sha
    with pytest.raises(FileExistsError):write_local_artifacts(report,results,output)


def test_failed_local_write_never_produces_completion_marker(synthetic,tmp_path):
    from dx27.research.evaluation import write_local_artifacts
    report,results=evaluate_synthetic(synthetic)
    results['R1'].daily[0]['bad_serialization']=float('nan')
    output=tmp_path/'partial'
    with pytest.raises(ValueError):write_local_artifacts(report,results,output)
    assert output.exists() and not (output/'completion.json').exists()


def test_blocked_synthetic_run_retains_profiles_without_profitability_claim(synthetic):
    # Remove one opening minute across all symbols: diagnostics retained, not dropped.
    at=synthetic.bars[0].timestamp
    damaged=IntradayDataset(tuple(b for b in synthetic.bars if b.timestamp!=at),synthetic.provenance)
    report,results=evaluate_synthetic(damaged)
    assert report['status']=='BLOCKED_SYNTHETIC_EVALUATION'
    assert report['primary_R1_net_return'] is None and not report['integrity_complete']
    assert set(results)=={'R0','R1','baseline'}
    assert results['R1'].quality


def test_r1_short_session_enforces_entry_cutoff(sessions):
    s=replace(sessions[0],closes_at=sessions[0].opens_at+15*MINUTE)
    m=OpeningDirectionFixture(s,'R1')
    for i in range(15):
        b=minute(s,i);m.on_closed_minute(b.timestamp,b,as_of=b.timestamp+MINUTE)
    assert 'ENTRY_CUTOFF' in [d['reason'] for d in m.decisions]
    assert not m.fills
