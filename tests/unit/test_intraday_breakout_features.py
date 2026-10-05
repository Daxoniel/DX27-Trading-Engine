from datetime import datetime, timedelta

import pytest

from dx27.core.models.market_context import MarketContext
from dx27.application.historical_replay import HistoricalReplay
from dx27.domains.intraday.bots.intraday_breakout import IntradayBreakoutBot
from dx27.domains.intraday.features.breakout_features import IntradayBreakoutFeatureCalculator


def bar(timestamp, high, low, close):
    return MarketContext("SPY", timestamp, "5m", close, high, low, close, 100)


def test_opening_range_uses_only_current_session_and_is_ready_at_ten():
    day = datetime(2026, 10, 1)
    bars = [bar(day - timedelta(days=1, hours=-9, minutes=-30), 999, 1, 10)]
    bars += [bar(day.replace(hour=9, minute=30), 101, 99, 100), bar(day.replace(hour=9, minute=55), 103, 98, 102)]
    calculator = IntradayBreakoutFeatureCalculator(atr_period=1, adx_period=1)
    before = calculator.calculate(bars)
    after = calculator.calculate(bars + [bar(day.replace(hour=10), 104, 100, 103)])
    assert not before.opening_range_ready
    assert (after.opening_range_low, after.opening_range_high) == (98, 103)
    assert after.opening_range_ready


def test_wilder_atr_matches_hand_calculation():
    start = datetime(2026, 10, 1, 9, 30)
    bars = [bar(start, 10, 8, 9), bar(start + timedelta(minutes=5), 12, 9, 11), bar(start + timedelta(minutes=10), 13, 10, 12), bar(start + timedelta(minutes=15), 15, 11, 14)]
    # True ranges are 3, 3, 4.  ATR(2) = ((3 + 3) / 2 * 1 + 4) / 2 = 3.5.
    assert IntradayBreakoutFeatureCalculator(atr_period=2, adx_period=2).calculate(bars).atr == pytest.approx(3.5)


def test_adx_warmup_and_monotonic_hand_fixture():
    start = datetime(2026, 10, 1, 9, 30)
    bars = [bar(start + timedelta(minutes=5 * index), 10 + index, 9 + index, 9.5 + index) for index in range(4)]
    calculator = IntradayBreakoutFeatureCalculator(atr_period=2, adx_period=2)
    assert calculator.calculate(bars[:3]).adx is None
    # Every directional movement is upward and each DX is 100, hence ADX(2)=100.
    features = calculator.calculate(bars)
    assert features.adx == pytest.approx(100)
    assert features.indicators_ready


def test_adx_14_is_ready_at_exact_wilder_boundary():
    start = datetime(2026, 9, 30, 9, 30)
    bars = [bar(start + timedelta(minutes=5 * index), 100 + index, 99 + index, 99.5 + index) for index in range(28)]
    calculator = IntradayBreakoutFeatureCalculator(atr_period=14, adx_period=14)

    assert calculator.calculate(bars[:27]).adx is None
    assert calculator.calculate(bars).adx == pytest.approx(100)


def test_future_bars_cannot_change_current_features():
    start = datetime(2026, 10, 1, 9, 30)
    prefix = [bar(start + timedelta(minutes=5 * index), 101 + index, 99 + index, 100 + index) for index in range(6)]
    future = bar(start + timedelta(minutes=30), 10_000, 1, 5_000)
    calculator = IntradayBreakoutFeatureCalculator(atr_period=2, adx_period=2)
    original = list(HistoricalReplay(prefix + [future]))[-2]
    changed = list(HistoricalReplay(prefix + [bar(future.timestamp, 20_000, 0, 10_000)]))[-2]
    assert calculator.calculate(original.history) == calculator.calculate(changed.history)


def test_future_bar_cannot_change_earlier_bot_signal():
    start = datetime(2026, 10, 1, 9, 30)
    prefix = [bar(start + timedelta(minutes=5 * index), 101 + index, 99 + index, 100.5 + index) for index in range(7)]
    future_timestamp = start + timedelta(minutes=35)
    original = list(HistoricalReplay(prefix + [bar(future_timestamp, 108, 106, 107)]))[-2]
    changed = list(HistoricalReplay(prefix + [bar(future_timestamp, 10_000, 0, 5_000)]))[-2]
    calculator = IntradayBreakoutFeatureCalculator(atr_period=2, adx_period=2)

    original_signal = IntradayBreakoutBot(adx_threshold=20).evaluate(
        original.context, calculator.calculate(original.history)
    )
    changed_signal = IntradayBreakoutBot(adx_threshold=20).evaluate(
        changed.context, calculator.calculate(changed.history)
    )

    assert original_signal is not None
    assert changed_signal == original_signal
