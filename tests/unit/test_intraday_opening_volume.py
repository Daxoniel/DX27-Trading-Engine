from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig, OpeningVolumeSelector
from dx27.intelligence.sentinel.session_calendar import TradingSession


def session(day, close="16:00"):
    ny = ZoneInfo("America/New_York")
    return TradingSession(day, datetime.fromisoformat(day + "T09:30").replace(tzinfo=ny),
                          datetime.fromisoformat(day + "T" + close).replace(tzinfo=ny))


def opening(selector, day, volumes, *, missing=(), zero=()):
    selector.begin_session(day)
    for minute in range(30):
        at = day.opens_at + timedelta(minutes=minute)
        bars = {s: MarketContext(s, at, "1m", 100, 101, 99, 100, 0 if (s, minute) in zero else v)
                for s, v in volumes.items() if (s, minute) not in missing}
        selector.observe_minute(at, bars)


def test_current_opening_is_excluded_from_denominator_and_symbols_are_independent():
    selector = OpeningVolumeSelector(["SPY", "QQQ"], OpeningVolumeConfig(2, 1.5))
    opening(selector, session("2025-11-24"), {"SPY": 100, "QQQ": 200})
    opening(selector, session("2025-11-25"), {"SPY": 300, "QQQ": 200})
    opening(selector, session("2025-11-26"), {"SPY": 300, "QQQ": 100})
    spy = next(r for r in selector.rows if r["session"] == "2025-11-26" and r["symbol"] == "SPY")
    assert spy["baseline_mean_volume"] == 6000
    assert spy["opening_volume"] == 9000
    assert spy["rvol"] == 1.5 and spy["selected"]
    assert spy["baseline_end"] == "2025-11-25"
    assert selector.selected == {"SPY"}
    assert all(r["reason"] == "INSUFFICIENT_HISTORY" for r in selector.rows[:4])


@pytest.mark.parametrize("gap", ["missing", "zero", "whole"])
def test_invalid_calendar_slots_are_not_skipped_and_age_out_only_after_lookback(gap):
    selector = OpeningVolumeSelector(["SPY"], OpeningVolumeConfig(2, 1))
    kwargs = {"missing": [("SPY", 4)]} if gap == "missing" else {"zero": [("SPY", 4)]} if gap == "zero" else {}
    opening(selector, session("2025-11-24"), {} if gap == "whole" else {"SPY": 100}, **kwargs)
    opening(selector, session("2025-11-25"), {"SPY": 100})
    opening(selector, session("2025-11-26"), {"SPY": 200})
    assert selector.rows[-1]["reason"] == "HISTORY_INCOMPLETE"
    assert selector.rows[-1]["rvol"] is None
    assert selector.rows[-1]["valid_baseline_sessions"] == 1
    opening(selector, session("2025-11-28", close="13:00"), {"SPY": 200})
    assert selector.rows[-1]["rvol"] == pytest.approx(4/3)
    assert selector.rows[-1]["selected"]


def test_selection_publishes_only_after_thirtieth_minute_and_ignores_later_volume():
    selector = OpeningVolumeSelector(["SPY"], OpeningVolumeConfig(1, 1))
    opening(selector, session("2025-11-25"), {"SPY": 100})
    day = session("2025-11-26")
    selector.begin_session(day)
    for minute in range(29):
        at = day.opens_at + timedelta(minutes=minute)
        selector.observe_minute(at, {"SPY": MarketContext("SPY", at, "1m", 100, 101, 99, 100, 200)})
        assert selector.selected == set() and not selector.finalized
        assert len(selector.rows) == 1
    at = day.opens_at + timedelta(minutes=29)
    selector.observe_minute(at, {"SPY": MarketContext("SPY", at, "1m", 100, 101, 99, 100, 200)})
    frozen = list(selector.rows)
    selector.observe_minute(day.opens_at + timedelta(minutes=30), {})
    assert selector.rows == frozen
    assert selector.rows[-1]["decision_at"] == day.opens_at.replace(hour=15, minute=0).isoformat()
    assert selector.rows[-1]["rvol"] == 2


def test_dst_and_early_close_keep_exactly_same_local_opening_interval():
    selector = OpeningVolumeSelector(["SPY"], OpeningVolumeConfig(1, 1))
    opening(selector, session("2025-03-07"), {"SPY": 100})
    opening(selector, session("2025-03-10"), {"SPY": 100})
    assert selector.rows[0]["decision_at"] == "2025-03-07T15:00:00+00:00"
    assert selector.rows[1]["decision_at"] == "2025-03-10T14:00:00+00:00"
    opening(selector, session("2025-11-28", close="13:00"), {"SPY": 100})
    assert selector.rows[-1]["observed_minutes"] == 30
    assert selector.rows[-1]["rvol"] == 1


def test_skipped_or_duplicate_opening_minutes_and_session_reordering_are_rejected():
    selector = OpeningVolumeSelector(["SPY"], OpeningVolumeConfig())
    day = session("2025-11-26")
    selector.begin_session(day)
    with pytest.raises(ValueError, match="every scheduled"):
        selector.observe_minute(day.opens_at + timedelta(minutes=1), {})
    with pytest.raises(ValueError, match="not completed"):
        selector.begin_session(session("2025-11-28"))


@pytest.mark.parametrize("values", [{"lookback_sessions": True}, {"lookback_sessions": 0},
                                    {"lookback_sessions": 1.5}, {"minimum_rvol": 0},
                                    {"minimum_rvol": float("nan")}, {"minimum_rvol": True}])
def test_invalid_selection_parameters_fail(values):
    with pytest.raises(ValueError):
        OpeningVolumeConfig(**values)


def test_finite_individual_volumes_cannot_produce_nonfinite_selection():
    selector = OpeningVolumeSelector(["SPY"], OpeningVolumeConfig())
    with pytest.raises(ValueError, match="sum must be finite"):
        opening(selector, session("2025-11-26"), {"SPY": 1e308})
