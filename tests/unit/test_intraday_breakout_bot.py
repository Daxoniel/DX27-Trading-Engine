from datetime import datetime

from dx27.core.models.bot_signal import SignalDirection
from dx27.core.models.feature_snapshot import FeatureSnapshot
from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.bots.intraday_breakout import (
    IntradayBreakoutBot,
)


def make_context(
    close=101.0,
    volume=1600,
    timestamp=None,
):
    if timestamp is None:
        timestamp = datetime(2026, 10, 1, 12, 0)

    return MarketContext(
        symbol="SPY",
        timestamp=timestamp,
        timeframe="5m",
        open=100.0,
        high=102.0,
        low=99.5,
        close=close,
        volume=volume,
    )


def make_features(
    previous_high_20=100.0,
    average_volume_20=1000,
):
    return FeatureSnapshot(
        previous_high_20=previous_high_20,
        average_volume_20=average_volume_20,
        atr_14=1.5,
    )


def test_bot_emits_long_when_all_rules_pass():
    bot = IntradayBreakoutBot()

    signal = bot.evaluate(
        make_context(
            close=101.0,
            volume=1600,
        ),
        make_features(
            previous_high_20=100.0,
            average_volume_20=1000,
        ),
    )

    assert signal is not None
    assert signal.symbol == "SPY"
    assert signal.direction == SignalDirection.LONG
    assert signal.bot_id == "intraday_breakout_v0_1"


def test_bot_emits_nothing_without_breakout():
    bot = IntradayBreakoutBot()

    signal = bot.evaluate(
        make_context(
            close=99.0,
            volume=1600,
        ),
        make_features(
            previous_high_20=100.0,
            average_volume_20=1000,
        ),
    )

    assert signal is None


def test_bot_emits_nothing_without_volume_confirmation():
    bot = IntradayBreakoutBot()

    signal = bot.evaluate(
        make_context(
            close=101.0,
            volume=1200,
        ),
        make_features(
            previous_high_20=100.0,
            average_volume_20=1000,
        ),
    )

    assert signal is None


def test_bot_emits_only_one_signal_per_day():
    bot = IntradayBreakoutBot()

    features = make_features(
        previous_high_20=100.0,
        average_volume_20=1000,
    )

    first_signal = bot.evaluate(
        make_context(
            close=101.0,
            volume=1600,
            timestamp=datetime(2026, 10, 1, 12, 0),
        ),
        features,
    )

    second_signal = bot.evaluate(
        make_context(
            close=102.0,
            volume=1800,
            timestamp=datetime(2026, 10, 1, 12, 5),
        ),
        features,
    )

    assert first_signal is not None
    assert second_signal is None


def test_bot_can_emit_again_on_next_day():
    bot = IntradayBreakoutBot()

    features = make_features(
        previous_high_20=100.0,
        average_volume_20=1000,
    )

    first_signal = bot.evaluate(
        make_context(
            close=101.0,
            volume=1600,
            timestamp=datetime(2026, 10, 1, 12, 0),
        ),
        features,
    )

    next_day_signal = bot.evaluate(
        make_context(
            close=101.5,
            volume=1700,
            timestamp=datetime(2026, 10, 2, 12, 0),
        ),
        features,
    )

    assert first_signal is not None
    assert next_day_signal is not None