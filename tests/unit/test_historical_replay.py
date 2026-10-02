from datetime import datetime, timedelta

from dx27.application.historical_replay import HistoricalReplay
from dx27.core.models.market_context import MarketContext


def bar(timestamp, close):
    return MarketContext("SPY", timestamp, "5m", close - 1, close + 1, close - 2, close, 100)


def test_replay_orders_bars_chronologically_and_exposes_only_prefixes():
    start = datetime(2026, 6, 15, 9, 30)
    bars = [bar(start + timedelta(minutes=10), 102), bar(start, 100), bar(start + timedelta(minutes=5), 101)]

    steps = list(HistoricalReplay(bars))

    assert [step.context.close for step in steps] == [100, 101, 102]
    assert [tuple(item.close for item in step.history) for step in steps] == [(100,), (100, 101), (100, 101, 102)]


def test_changing_a_future_bar_cannot_change_an_earlier_replay_step():
    start = datetime(2026, 6, 15, 9, 30)
    original = [bar(start, 100), bar(start + timedelta(minutes=5), 101), bar(start + timedelta(minutes=10), 102)]
    changed_future = [bar(start, 100), bar(start + timedelta(minutes=5), 101), bar(start + timedelta(minutes=10), 999)]

    original_step = list(HistoricalReplay(original))[1]
    changed_step = list(HistoricalReplay(changed_future))[1]

    assert original_step == changed_step


def test_replay_rejects_duplicate_timestamps():
    timestamp = datetime(2026, 6, 15, 9, 30)
    try:
        HistoricalReplay([bar(timestamp, 100), bar(timestamp, 101)])
    except ValueError as error:
        assert "unique timestamps" in str(error)
    else:
        raise AssertionError("duplicate timestamp should be rejected")
