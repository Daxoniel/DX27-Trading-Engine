from datetime import datetime

import pytest

from dx27.core.interfaces.intraday_bot import IntradayBot
from dx27.core.models.bot_signal import SignalDirection
from dx27.core.models.feature_snapshot import FeatureSnapshot
from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.bots.intraday_breakout import IntradayBreakoutBot


def context(close=101, timestamp=datetime(2026, 10, 1, 10, 5)):
    return MarketContext("SPY", timestamp, "5m", 100, 102, 99, close, 100)


def features(**changes):
    values = dict(opening_range_high=100, opening_range_low=90, opening_range_ready=True, atr=1.5, adx=30, indicators_ready=True)
    values.update(changes)
    return FeatureSnapshot(**values)


def test_bot_is_the_intraday_bot_named_tanyuan_and_generates_both_directions():
    bot = IntradayBreakoutBot()
    assert isinstance(bot, IntradayBot)
    long_signal = bot.evaluate(context(101), features())
    assert long_signal.bot_id == "tanyuan_orb"
    assert long_signal.direction == SignalDirection.LONG
    short_signal = IntradayBreakoutBot().evaluate(context(89), features())
    assert short_signal.direction == SignalDirection.SHORT


@pytest.mark.parametrize("snapshot", [features(opening_range_ready=False), features(indicators_ready=False), features(adx=20), features()])
def test_bot_rejects_incomplete_or_warmup_adx_or_inside_range(snapshot):
    close = 95 if snapshot == features() else 101
    assert IntradayBreakoutBot().evaluate(context(close), snapshot) is None


def test_bot_limits_entries_to_one_per_session_and_regular_hours():
    bot = IntradayBreakoutBot()
    assert bot.evaluate(context(101), features()) is not None
    assert bot.evaluate(context(102, datetime(2026, 10, 1, 10, 10)), features()) is None
    assert bot.evaluate(context(101, datetime(2026, 10, 2, 10, 5)), features()) is not None
    assert IntradayBreakoutBot().evaluate(context(101, datetime(2026, 10, 1, 16, 0)), features()) is None
