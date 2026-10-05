from dataclasses import dataclass
from datetime import datetime

from dx27.adapters.simulated.account import SimulatedAccountAdapter
from dx27.adapters.simulated.execution import SimulatedExecutionAdapter
from dx27.adapters.simulated.portfolio import SimulatedPortfolioAdapter
from dx27.application.historical_replay import HistoricalReplay, NextBarExecutionScheduler
from dx27.core.models.market_context import MarketContext
from dx27.core.models.portfolio_target import PortfolioTarget
from dx27.core.models.trade_intent import TradeIntent, TradeSide
from dx27.domains.intraday.trade_management.trade_manager import (
    IntradayTradeManager,
)
from dx27.execution_planning.target_to_intent import TargetToIntentPlanner


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


def test_end_of_day_decision_queues_exit_for_next_bar_open():
    account = SimulatedAccountAdapter(1_000)
    portfolio = SimulatedPortfolioAdapter()
    account.attach_portfolio(portfolio)
    execution = SimulatedExecutionAdapter(account, portfolio)
    execution.set_fill_context(datetime(2026, 10, 1, 14, 0), {"SPY": 100})
    execution.execute(TradeIntent("tanyuan_orb", "SPY", TradeSide.BUY, quantity=1))
    trade = IntradayTradeManager(
        symbol="SPY",
        entry_time=datetime(2026, 10, 1, 14, 0),
        entry_price=100.0,
        atr=1.0,
    )
    decision_bar = MarketContext("SPY", datetime(2026, 10, 1, 15, 50), "5m", 100.2, 100.8, 99.5, 100.4, 100)
    fill_bar = MarketContext("SPY", datetime(2026, 10, 1, 15, 55), "5m", 101.5, 102, 101, 101.8, 100)
    decision_step, fill_step = HistoricalReplay([decision_bar, fill_bar])
    scheduler = NextBarExecutionScheduler(execution)

    scheduler.begin_step(decision_step)
    assert trade.update(decision_bar.timestamp, decision_bar) is None
    assert trade.end_of_day_exit_due(decision_bar.timestamp)
    exit_intent = TargetToIntentPlanner().plan(
        PortfolioTarget("SPY", target_quantity=0, source_strategy="tanyuan_orb", reason=("end_of_day",)),
        portfolio.get_portfolio_snapshot(),
    )
    scheduler.queue([exit_intent])
    reports = scheduler.begin_step(fill_step)

    assert reports[0].timestamp == datetime(2026, 10, 1, 15, 55)
    assert reports[0].average_fill_price == 101.5
    assert reports[0].average_fill_price != decision_bar.close
    assert portfolio.get_portfolio_snapshot().positions == ()
