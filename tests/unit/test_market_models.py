from datetime import datetime

from dx27.core.models.market_context import MarketContext
from dx27.core.models.feature_snapshot import FeatureSnapshot


def test_market_context_keeps_market_data():
    context = MarketContext(
        symbol="SPY",
        timestamp=datetime(2026, 10, 1, 10, 35),
        timeframe="5m",
        open=575.20,
        high=575.80,
        low=575.10,
        close=575.70,
        volume=840000,
    )

    assert context.symbol == "SPY"
    assert context.timeframe == "5m"
    assert context.close == 575.70
    assert context.volume == 840000


def test_feature_snapshot_keeps_features():
    features = FeatureSnapshot(
        previous_high_20=575.00,
        average_volume_20=500000,
        atr_14=1.80,
    )

    assert features.previous_high_20 == 575.00
    assert features.average_volume_20 == 500000
    assert features.atr_14 == 1.80