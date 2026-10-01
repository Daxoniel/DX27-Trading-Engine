from dataclasses import dataclass
from datetime import datetime

from dx27.strategies.plugins.intraday.trade_manager import (
    IntradayTradeManager,
)


@dataclass
class BarStub:
    high: float
    low: float
    close: float


def test_trade_exits_at_take_profit():
    trade = IntradayTradeManager(
        symbol="SPY",
        entry_time=datetime(2026, 10, 1, 12, 0),
        entry_price=100.0,
        atr=1.0,
    )

    result = trade.update(
        datetime(2026, 10, 1, 12, 5),
        BarStub(
            high=102.2,
            low=100.2,
            close=101.8,
        ),
    )

    assert result is not None
    assert result.exit_price == 102.0
    assert result.exit_reason == "take_profit"
    assert result.pnl == 2.0


def test_trade_exits_at_stop_loss():
    trade = IntradayTradeManager(
        symbol="SPY",
        entry_time=datetime(2026, 10, 1, 12, 0),
        entry_price=100.0,
        atr=1.0,
    )

    result = trade.update(
        datetime(2026, 10, 1, 12, 5),
        BarStub(
            high=100.5,
            low=98.8,
            close=99.0,
        ),
    )

    assert result is not None
    assert result.exit_price == 99.0
    assert result.exit_reason == "stop_loss"
    assert result.pnl == -1.0


def test_trade_exits_at_end_of_day():
    trade = IntradayTradeManager(
        symbol="SPY",
        entry_time=datetime(2026, 10, 1, 14, 0),
        entry_price=100.0,
        atr=1.0,
    )

    result = trade.update(
        datetime(2026, 10, 1, 15, 50),
        BarStub(
            high=100.8,
            low=99.5,
            close=100.4,
        ),
    )

    assert result is not None
    assert result.exit_price == 100.4
    assert result.exit_reason == "end_of_day"