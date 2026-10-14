from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.features.breakout_features import IntradayBreakoutFeatureCalculator
from dx27.domains.intraday.features.streaming_breakout import StreamingBreakoutFeatures


def sequence(count=100):
    start = datetime(2025, 11, 26, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    return [MarketContext("SPY", start + timedelta(minutes=5*i), "5m", 100 + i % 7,
                          102 + i % 7, 98 + i % 7, 100.5 + i % 7, 1000) for i in range(count)]


@pytest.mark.parametrize("atr_period,adx_period", [(14, 14), (2, 3), (1, 1)])
def test_incremental_wilder_values_match_batch_prefixes(atr_period, adx_period):
    bars = sequence()
    stream = StreamingBreakoutFeatures(atr_period, adx_period)
    batch = IntradayBreakoutFeatureCalculator(atr_period, adx_period)
    for index, bar in enumerate(bars):
        incremental = stream.add(bar, as_of=bar.timestamp + timedelta(minutes=5))
        expected = batch.calculate(bars[:index+1])
        assert incremental.atr == pytest.approx(expected.atr) if expected.atr is not None else incremental.atr is None
        assert incremental.adx == pytest.approx(expected.adx) if expected.adx is not None else incremental.adx is None


def test_complete_opening_range_becomes_ready_at_completion_not_interval_start():
    bars = sequence(6)
    stream = StreamingBreakoutFeatures(2, 2)
    results = [stream.add(b, as_of=b.timestamp + timedelta(minutes=5)) for b in bars]
    assert not any(f.opening_range_ready for f in results[:-1])
    assert results[-1].opening_range_ready
    incomplete = StreamingBreakoutFeatures(2, 2)
    results = [incomplete.add(b, as_of=b.timestamp + timedelta(minutes=5)) for b in bars[1:]]
    assert not results[-1].opening_range_ready


def test_stream_rejects_future_as_of_and_mixed_symbol_state():
    bars = sequence(2)
    stream = StreamingBreakoutFeatures()
    with pytest.raises(ValueError, match="complete"):
        stream.add(bars[0], as_of=bars[0].timestamp)
    stream.add(bars[0], as_of=bars[0].timestamp + timedelta(minutes=5))
    other = MarketContext("QQQ", bars[1].timestamp, "5m", 100, 101, 99, 100, 1000)
    with pytest.raises(ValueError, match="one symbol"):
        stream.add(other, as_of=other.timestamp + timedelta(minutes=5))
