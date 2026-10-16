from datetime import date
from dataclasses import replace
import json
import pytest

from contrasts import ContrastFixture, run_arm, json_bytes, verify_reference
from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.core.models.market_context import MarketContext
from dx27.research.opening_direction import MINUTE
from dx27.research.multisession import OpeningDirectionSequence
from dx27.research.statistics import audit_result


@pytest.fixture
def sessions():
    return load_xnys_calendar(date(2025, 3, 10), date(2025, 3, 11)).sessions


def make_bars(sessions, opening_close=100.5):
    out = {}
    for s in sessions:
        for i in range(int((s.closes_at-s.opens_at)/MINUTE)):
            at = s.opens_at+i*MINUTE
            out[at] = MarketContext('QQQ', at, '1m', 100., 101. if i < 5 else 100.6,
                99. if i < 5 else 99.5, opening_close if i < 5 else 100.2, 100000.)
    return out


def feed_to(model, bars, until):
    while model.next_at < until:
        at = model.next_at
        model.on_closed_minute(at, bars[at], as_of=at+MINUTE)


def test_reference_matches_original_sequence_all_records(sessions, tmp_path):
    bars = make_bars(sessions)
    original = OpeningDirectionSequence(sessions, 'R0')
    while original.next_at is not None:
        at = original.next_at
        original.on_closed_minute(at, bars[at], as_of=at+MINUTE)
    result = original.result()
    for kind in ('daily', 'fills', 'trades', 'equity', 'decisions', 'quality'):
        (tmp_path/f'R0-{kind}.json').write_bytes(json_bytes(getattr(result, kind)))
    current = run_arm(sessions, bars, 'R0')
    verify_reference(current, tmp_path)
    changed = json.loads((tmp_path/'R0-trades.json').read_bytes())
    changed[0]['net_pnl'] += .01
    (tmp_path/'R0-trades.json').write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ValueError, match='REFERENCE_REPRODUCTION_MISMATCH'):
        verify_reference(current, tmp_path)


def test_long_only_removes_shorts_but_reference_keeps_them(sessions):
    bars = make_bars(sessions, opening_close=99.5)
    assert len(run_arm(sessions, bars, 'R0').trades) == 2
    result = run_arm(sessions, bars, 'LONG_ONLY')
    assert not result.fills
    assert all(d['reason'] == 'SHORT_DISABLED' for d in result.decisions)
    assert result.summary['ending_cash'] == 25000


def test_delay_does_not_enter_at_first_available_open(sessions):
    s = sessions[0]; bars = make_bars([s])
    m = ContrastFixture(s, 'DELAY_1M')
    feed_to(m, bars, s.opens_at+6*MINUTE)
    assert not m.fills
    feed_to(m, bars, s.opens_at+7*MINUTE)
    assert m.fills[0].at == s.opens_at+6*MINUTE


def test_delay_rejects_nonpositive_r_without_retry(sessions):
    s = sessions[0]; bars = make_bars([s]); at = s.opens_at+6*MINUTE
    bars[at] = replace(bars[at], open=98., high=98.2, low=97.8, close=98.)
    r = run_arm([s], bars, 'DELAY_1M')
    assert not r.fills
    assert r.decisions[-1]['reason'] == 'NONPOSITIVE_R'


@pytest.mark.parametrize('change,reason,reference', [
    (dict(low=98.), 'SCHEDULED_FLATTEN', 100.),
    (dict(open=98., high=98.2, low=97.8, close=98.), 'GAP_STOP', 98.),
    (dict(open=111., high=112., low=110., close=111.), 'GAP_TARGET_CAPPED', 110.),
])
def test_early_close_priority(sessions, change, reason, reference):
    s = sessions[0]; bars = make_bars([s]); at = s.closes_at-5*MINUTE
    bars[at] = replace(bars[at], **change)
    r = run_arm([s], bars, 'EARLY_CLOSE')
    assert r.fills[-1]['reason'] == reason
    assert r.fills[-1]['at'] == at
    assert r.fills[-1]['reference'] == reference
    audit_result(r, [s])


def test_halfday_uses_calendar_close():
    s = load_xnys_calendar(date(2025, 11, 27), date(2025, 11, 28)).sessions[0]
    r = run_arm([s], make_bars([s]), 'EARLY_CLOSE')
    assert r.fills[-1]['at'] == s.closes_at-5*MINUTE
    assert len(r.equity) == 210


def test_capital_carries_between_days_and_audits(sessions):
    r = run_arm(sessions, make_bars(sessions), 'LONG_ONLY')
    assert r.daily[0]['ending_equity'] > 25000
    assert r.daily[1]['starting_equity'] == r.daily[0]['ending_equity']
    audit_result(r, sessions)


def test_missing_minute_blocks_whole_arm(sessions):
    bars = make_bars(sessions); del bars[sessions[0].opens_at+10*MINUTE]
    with pytest.raises(ValueError, match='INCOMPLETE_OR_NONPOSITIVE_CAPITAL'):
        run_arm(sessions, bars, 'R0')


def test_future_bar_extremes_do_not_change_entry(sessions):
    s = sessions[0]; bars = make_bars([s]); changed = dict(bars)
    at = s.opens_at+6*MINUTE
    changed[at] = replace(bars[at], high=120., low=98., volume=1.)
    a = run_arm([s], bars, 'DELAY_1M'); b = run_arm([s], changed, 'DELAY_1M')
    assert a.fills[0] == b.fills[0]
    assert b.fills[-1]['reason'] == 'AMBIGUOUS_STOP_FIRST'


def test_unknown_arm_and_checkpoint_rejected(sessions):
    with pytest.raises(ValueError, match='UNKNOWN_FIXED_ARM'):
        ContrastFixture(sessions[0], 'WINNER')
    with pytest.raises(ValueError, match='CHECKPOINT_NOT_SUPPORTED'):
        ContrastFixture(sessions[0], 'R0').checkpoint()
