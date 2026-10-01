from dataclasses import dataclass

from dx27.domains.intraday.features.breakout_features import (
    IntradayBreakoutFeatureCalculator,
)


@dataclass
class BarStub:
    high: float
    low: float
    close: float
    volume: float


def test_feature_calculator_builds_features():
    bars = []

    for i in range(20):
        bars.append(
            BarStub(
                high=100 + i * 0.1,
                low=99 + i * 0.1,
                close=99.5 + i * 0.1,
                volume=1000,
            )
        )

    bars.append(
        BarStub(
            high=103.0,
            low=101.0,
            close=102.5,
            volume=2000,
        )
    )

    calculator = IntradayBreakoutFeatureCalculator()
    features = calculator.calculate(bars)

    assert features.previous_high_20 == 101.9
    assert features.average_volume_20 == 1000
    assert features.atr_14 > 0