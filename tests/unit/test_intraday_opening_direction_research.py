"""Synthetic-only acceptance: no market files, network or return selection."""

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.core.models.market_context import MarketContext
from dx27.research.opening_direction import OpeningDirectionFixture, MINUTE


@pytest.fixture
def session():
    return load_xnys_calendar(date(2025, 3, 7), date(2025, 3, 12)).get("2025-03-10")


def bar(session, minute, **changes):
    values = dict(symbol="QQQ", timestamp=session.opens_at + minute * MINUTE,
                  timeframe="1m", open=100., high=101., low=99., close=100.5,
                  volume=100_000.)
    values.update(changes)
    return MarketContext(**values)


def feed(model, minute, **changes):
    b = bar(model.session, minute, **changes)
    model.on_closed_minute(b.timestamp, b, as_of=b.timestamp + MINUTE)


def opening(model, **changes):
    for i in range(5):
        feed(model, i, **changes)


def finish(model, **changes):
    while model.next_at < model.session.closes_at:
        i = int((model.next_at - model.session.opens_at) / MINUTE)
        feed(model, i, **changes)
    return model.report()


def test_signal_only_after_five_completed_minutes_and_r1_delays_entry(session):
    m = OpeningDirectionFixture(session, "R1")
    for i in range(4):
        feed(m, i)
        assert not m.decisions and not m.fills
    feed(m, 4)
    assert m.decisions == [dict(at=m.signal_at.isoformat(), reason="LONG")]
    assert not m.fills
    feed(m, 5, low=99.5)
    assert not m.fills
    feed(m, 6, low=99.5)
    assert m.fills[0].at == session.opens_at + 6 * MINUTE
    assert m.quantity > 0


@pytest.mark.parametrize("profile,close,reason", [
    ("R0", 100.5, "LONG"), ("R0", 99.5, "SHORT"),
    ("R1", 99.5, "SHORT_DISABLED"), ("R0", 100., "DOJI"),
])
def test_opening_direction_without_breakout_or_adx(session, profile, close, reason):
    m = OpeningDirectionFixture(session, profile)
    opening(m, close=close)
    assert m.decisions[-1]["reason"] == reason
    r = finish(m, low=99.5, high=100.5, close=100.)
    assert r["closed_trades"] == int(reason in ("LONG", "SHORT"))
    assert r["status"] == "COMPLETE_FIXTURE"


@pytest.mark.parametrize("close,exit_high,exit_low,reason", [
    (100.5, 111., 99.5, "TARGET"), (100.5, 100.5, 98., "STOP"),
    (100.5, 111., 98., "AMBIGUOUS_STOP_FIRST"),
    (99.5, 100.5, 89., "TARGET"), (99.5, 102., 99.5, "STOP"),
    (99.5, 102., 89., "AMBIGUOUS_STOP_FIRST"),
])
def test_long_and_short_exit_paths_reconcile(session, close, exit_high, exit_low, reason):
    m = OpeningDirectionFixture(session, "R0")
    opening(m, close=close)
    feed(m, 5, high=100.5, low=99.5, close=100.)
    feed(m, 6, high=exit_high, low=exit_low, close=100.)
    assert m.fills[-1].reason == reason
    assert m.ambiguous_minutes == int(reason == "AMBIGUOUS_STOP_FIRST")
    r = finish(m)
    assert r["cash"] == pytest.approx(r["equity"])
    assert r["realized_pnl"] == pytest.approx(r["gross_pnl"] - r["commission"])
    assert r["quantity"] == 0 and len(m.fills) == 2


@pytest.mark.parametrize("close,reference", [(100.5, 97.), (99.5, 103.)])
def test_gap_stop_executes_at_adverse_open_not_guaranteed_stop(session, close, reference):
    m = OpeningDirectionFixture(session, "R0")
    opening(m, close=close)
    feed(m, 5, low=99.5, high=100.5, close=100.)
    feed(m, 6, open=reference, low=reference-.1, high=reference+.1, close=reference)
    assert m.fills[-1].reason == "GAP_STOP"
    assert m.fills[-1].reference == reference
    assert m.report()["realized_pnl"] < -m.report()["planned_stop_risk"]


def test_cost_aware_sizing_cash_position_and_prior_volume_caps(session):
    m = OpeningDirectionFixture(session, "R1")
    opening(m)
    feed(m, 5, volume=300., low=99.5)
    feed(m, 6, volume=1_000_000., low=99.5)
    assert m.quantity == 3  # entry-minute volume cannot enlarge this
    assert m.planned_risk <= 250
    assert m.cash >= 0
    assert m.fills[0].quantity * m.fills[0].price <= 25_000
    r = finish(m, low=99.5, high=100.5, close=100.)
    assert r["realized_pnl"] == pytest.approx(
        r["gross_pnl"] - r["commission"] - r["spread_cost"] - r["slippage_cost"])
    assert r["commission"] == pytest.approx(.70)
    assert r["spread_cost"] > 0 and r["slippage_cost"] > 0
    assert r["effectiveness"] == "NOT_EVALUATED" and not r["execution_enabled"]


def test_r1_fee_risk_caps_are_enforced_at_stop(session):
    m = OpeningDirectionFixture(session, "R1")
    opening(m)
    feed(m, 5, low=99.5)
    feed(m, 6, low=98.)
    r = m.report()
    assert 0 < r["planned_stop_risk"] <= 250
    assert -r["realized_pnl"] == pytest.approx(r["planned_stop_risk"])


@pytest.mark.parametrize("minute,kind", [(2, "missing"), (2, "zero"), (5, "missing"), (6, "zero")])
def test_bad_data_blocks_entry_without_searching_another_minute(session, minute, kind):
    m = OpeningDirectionFixture(session, "R1")
    for i in range(8):
        if i == minute and kind == "missing":
            m.on_closed_minute(m.next_at, None, as_of=m.next_at + MINUTE)
        else:
            feed(m, i, volume=0. if i == minute else 100_000.)
    assert not m.fills
    assert finish(m)["status"] == "INCOMPLETE_FIXTURE"


def test_missing_data_with_position_cannot_claim_complete(session):
    m = OpeningDirectionFixture(session, "R0")
    opening(m)
    feed(m, 5, low=99.5)
    m.on_closed_minute(m.next_at, None, as_of=m.next_at + MINUTE)
    assert m.report()["quantity"] > 0
    r = finish(m, low=99.5)
    assert r["status"] == "INCOMPLETE_FIXTURE" and not r["data_valid"]


@pytest.mark.parametrize("case,reason", [("flat", "ZERO_RANGE"), ("gap", "NONPOSITIVE_R"),
                                         ("tiny_volume", "ZERO_QUANTITY")])
def test_explicit_no_trade_reasons(session, case, reason):
    m = OpeningDirectionFixture(session, "R1")
    opening(m, **(dict(open=100., high=100., low=100., close=100.) if case == "flat" else {}))
    feed(m, 5, volume=1. if case == "tiny_volume" else 100_000.)
    feed(m, 6, **(dict(open=98., low=97., high=99., close=98.) if case == "gap" else {}))
    assert reason in [d["reason"] for d in m.decisions]
    assert not m.fills


def test_restart_from_json_prefix_does_not_repeat_entry_or_change_ledger(session):
    a = OpeningDirectionFixture(session, "R1")
    opening(a)
    feed(a, 5, low=99.5)
    feed(a, 6, low=99.5)
    checkpoint = json.loads(json.dumps(a.checkpoint()))
    b = OpeningDirectionFixture.restore(checkpoint, session=session, profile="R1")
    assert a.fills == b.fills and a.decisions == b.decisions
    previous = bar(session, 6, low=99.5)
    with pytest.raises(ValueError):
        b.on_closed_minute(previous.timestamp, previous, as_of=previous.timestamp + MINUTE)
    assert finish(a, low=99.5) == finish(b, low=99.5)
    assert len(a.fills) == len(b.fills) == 2
    with pytest.raises(ValueError, match="mismatch"):
        OpeningDirectionFixture.restore(checkpoint, session=session, profile="R0")


def test_future_mutation_cannot_change_frozen_signal_or_entry_plan(session):
    models = [OpeningDirectionFixture(session, "R1") for _ in range(2)]
    for m in models:
        opening(m)
        feed(m, 5, low=99.5)
    feed(models[0], 6, high=100.5, low=99.5, volume=1.)
    feed(models[1], 6, high=120., low=98., volume=1_000_000.)
    a, b = models
    assert a.decisions == b.decisions
    assert a.fills[0] == b.fills[0]
    assert a.target == b.target and a.planned_risk == b.planned_risk
    assert not a.quantity == b.quantity  # future high/low may change exits, never entry


@pytest.mark.parametrize("case", ["early", "wrong_symbol", "naive", "nan", "out_of_order"])
def test_invalid_input_does_not_mutate_checkpoint(session, case):
    m = OpeningDirectionFixture(session, "R0")
    original = m.checkpoint()
    b = bar(session, 0)
    as_of = b.timestamp + MINUTE
    if case == "early": as_of = b.timestamp
    if case == "wrong_symbol": b = replace(b, symbol="SPY")
    if case == "naive": b = replace(b, timestamp=b.timestamp.replace(tzinfo=None))
    if case == "nan": b = replace(b, close=float("nan"))
    if case == "out_of_order": b = replace(b, timestamp=b.timestamp + MINUTE)
    with pytest.raises(ValueError):
        m.on_closed_minute(b.timestamp, b, as_of=as_of)
    assert m.checkpoint() == original


def test_r0_ideal_close_and_r1_scheduled_flatten(session):
    for profile,reason in [("R0", "SESSION_CLOSE_IDEALIZED"), ("R1", "SCHEDULED_FLATTEN")]:
        m = OpeningDirectionFixture(session, profile)
        opening(m)
        r = finish(m, low=99.5, high=100.5, close=100.)
        assert r["status"] == "COMPLETE_FIXTURE"
        assert m.fills[-1].reason == reason
        assert m.fills[-1].at == (session.closes_at if profile == "R0" else session.closes_at - 5*MINUTE)


def test_calendar_dst_and_half_day_boundaries():
    c = load_xnys_calendar(date(2025, 3, 7), date(2025, 3, 10))
    assert c.get("2025-03-07").opens_at.hour == 14
    assert c.get("2025-03-10").opens_at.hour == 13
    s = load_xnys_calendar(date(2025, 11, 26), date(2025, 11, 28)).get("2025-11-28")
    m = OpeningDirectionFixture(s, "R1")
    opening(m)
    assert finish(m, low=99.5)["processed_minutes"] == 210
    assert m.fills[-1].at == s.closes_at - timedelta(minutes=5)


def test_session_checkpoint_and_profile_rejection(session):
    with pytest.raises(ValueError): OpeningDirectionFixture(session, "live")
    with pytest.raises(ValueError): OpeningDirectionFixture(replace(session, opens_at=session.opens_at+MINUTE), "R0")
    m = OpeningDirectionFixture(session, "R0")
    c = m.checkpoint()
    c["ticks"] = [None] * 391
    with pytest.raises(ValueError): OpeningDirectionFixture.restore(c, session=session, profile="R0")


@pytest.mark.parametrize("close,exit_open,expected", [(100.5, 115., 110.), (99.5, 85., 90.)])
def test_favorable_target_gap_is_capped_not_optimistically_filled(session, close, exit_open, expected):
    m = OpeningDirectionFixture(session, "R0")
    opening(m, close=close)
    feed(m, 5, low=99.5, high=100.5, close=100.)
    feed(m, 6, open=exit_open, low=exit_open-.1, high=exit_open+.1, close=exit_open)
    assert m.fills[-1].reason == "GAP_TARGET_CAPPED"
    assert m.fills[-1].reference == expected
    m.report()


def test_checkpoint_is_a_detached_copy_and_corrupt_prefix_is_rejected(session):
    m = OpeningDirectionFixture(session, "R0")
    opening(m)
    before = m.checkpoint()
    changed = m.checkpoint()
    changed["ticks"][0]["close"] = 123.
    assert m.checkpoint() == before
    with pytest.raises(ValueError):
        OpeningDirectionFixture.restore(changed, session=session, profile="R0")
    changed = m.checkpoint()
    changed["version"] = "future-version"
    with pytest.raises(ValueError):
        OpeningDirectionFixture.restore(changed, session=session, profile="R0")


def test_reference_position_is_capped_by_four_times_equity(session):
    m = OpeningDirectionFixture(session, "R0")
    opening(m, open=100., high=100.01, low=99.99, close=100.005)
    feed(m, 5, high=100.005, low=99.995, close=100.)
    assert m.quantity == 1000
    assert m.fills[0].quantity * m.fills[0].price == 4 * m.initial_cash


def test_missing_flatten_and_close_do_not_manufacture_a_fill(session):
    m = OpeningDirectionFixture(session, "R1")
    opening(m)
    while m.next_at < m.flatten_at:
        feed(m, int((m.next_at-session.opens_at)/MINUTE), low=99.5)
    while m.next_at < session.closes_at:
        m.on_closed_minute(m.next_at, None, as_of=m.next_at+MINUTE)
    r = m.report()
    assert r["status"] == "INCOMPLETE_FIXTURE" and r["quantity"] > 0
    assert len(m.fills) == 1 and r["closed_trades"] == 0
