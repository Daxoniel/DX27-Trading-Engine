from dataclasses import dataclass
from datetime import datetime

from dx27.core.models.market_context import MarketContext
from dx27.features.intraday_breakout_features import (
    IntradayBreakoutFeatureCalculator,
)
from dx27.strategies.plugins.intraday.intraday_breakout import (
    IntradayBreakoutBot,
)


@dataclass
class BarStub:
    open: float
    high: float
    low: float
    close: float
    volume: float


def test_intraday_breakout_end_to_end():
    bars = []

    # 前20根：最高价逐渐到101.9，成交量恒定1000
    for i in range(20):
        bars.append(
            BarStub(
                open=99.5 + i * 0.1,
                high=100.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=99.5 + i * 0.1,
                volume=1000,
            )
        )

    # 第21根：真正产生突破 + 放量
    current_bar = BarStub(
        open=101.8,
        high=103.0,
        low=101.5,
        close=102.5,
        volume=2000,
    )

    bars.append(current_bar)

    # 1. 自动计算Feature
    calculator = IntradayBreakoutFeatureCalculator()
    features = calculator.calculate(bars)

    # 2. 把当前bar包装成DX27自己的MarketContext
    context = MarketContext(
        symbol="SPY",
        timestamp=datetime(2026, 10, 1, 10, 35),
        timeframe="5m",
        open=current_bar.open,
        high=current_bar.high,
        low=current_bar.low,
        close=current_bar.close,
        volume=current_bar.volume,
    )

    # 3. Bot做决策
    bot = IntradayBreakoutBot()
    signal = bot.evaluate(context, features)

    # 4. 检查最终结果
    assert signal is not None
    assert signal.symbol == "SPY"
    assert signal.direction.value == "long"