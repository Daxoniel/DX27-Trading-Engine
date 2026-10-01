from datetime import datetime

from dx27.core.models.market_context import MarketContext
from dx27.core.models.feature_snapshot import FeatureSnapshot
from dx27.rules.packs.breakout_rule import BreakoutRule
from dx27.rules.packs.volume_confirmation_rule import VolumeConfirmationRule


def make_context(close=101.0, volume=1500):
    return MarketContext(
        symbol="SPY",
        timestamp=datetime(2026, 10, 1, 10, 35),
        timeframe="5m",
        open=100.0,
        high=102.0,
        low=99.5,
        close=close,
        volume=volume,
    )


def make_features(previous_high_20=100.0, average_volume_20=1000):
    return FeatureSnapshot(
        previous_high_20=previous_high_20,
        average_volume_20=average_volume_20,
        atr_14=1.5,
    )


def test_breakout_rule_passes():
    result = BreakoutRule().evaluate(
        make_context(close=101.0),
        make_features(previous_high_20=100.0),
    )

    assert result.triggered is True


def test_breakout_rule_fails():
    result = BreakoutRule().evaluate(
        make_context(close=99.0),
        make_features(previous_high_20=100.0),
    )

    assert result.triggered is False


def test_volume_confirmation_passes():
    result = VolumeConfirmationRule().evaluate(
        make_context(volume=1600),
        make_features(average_volume_20=1000),
    )

    assert result.triggered is True
    assert result.score == 1.6


def test_volume_confirmation_fails():
    result = VolumeConfirmationRule().evaluate(
        make_context(volume=1200),
        make_features(average_volume_20=1000),
    )

    assert result.triggered is False