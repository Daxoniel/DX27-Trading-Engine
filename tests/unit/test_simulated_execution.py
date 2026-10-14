from datetime import datetime, timedelta

import pytest

from dx27.adapters.simulated.account import SimulatedAccountAdapter
from dx27.adapters.simulated.execution import SimulatedExecutionAdapter
from dx27.adapters.simulated.portfolio import SimulatedPortfolioAdapter
from dx27.application.historical_replay import HistoricalReplay, NextBarExecutionScheduler
from dx27.core.models.execution_report import ExecutionReport
from dx27.core.models.market_context import MarketContext
from dx27.core.models.portfolio_target import PortfolioTarget
from dx27.core.models.trade_intent import TradeIntent, TradeSide
from dx27.execution_planning.target_to_intent import TargetToIntentPlanner
from dx27.core.models.execution_costs import ExecutionCosts


def make_system(cash=1_000, slippage_bps=0):
    account = SimulatedAccountAdapter(cash)
    portfolio = SimulatedPortfolioAdapter()
    account.attach_portfolio(portfolio)
    return account, portfolio, SimulatedExecutionAdapter(account, portfolio, slippage_bps)


def intent(side, quantity):
    return TradeIntent("探员", "SPY", side, quantity=quantity)


def test_intent_created_at_bar_n_fills_at_bar_n_plus_one_open_with_slippage():
    account, portfolio, execution = make_system(slippage_bps=10)
    start = datetime(2026, 6, 15, 9, 30)
    bars = [
        MarketContext("SPY", start, "5m", 100, 101, 99, 100, 100),
        MarketContext("SPY", start + timedelta(minutes=5), "5m", 110, 111, 109, 110, 100),
    ]
    scheduler = NextBarExecutionScheduler(execution)
    steps = list(HistoricalReplay(bars))

    assert scheduler.process_step(steps[0], [intent(TradeSide.BUY, 2)]) == ()
    reports = scheduler.process_step(steps[1])

    assert reports[0].average_fill_price == pytest.approx(110.11)
    assert reports[0].timestamp == steps[1].context.timestamp
    assert account.get_account_snapshot().cash == pytest.approx(779.78)
    assert portfolio.get_portfolio_snapshot().positions[0].quantity == 2


def test_simulated_sell_close_updates_cash_and_removes_position():
    account, portfolio, execution = make_system()
    execution.set_fill_context(datetime(2026, 6, 15, 9, 35), {"SPY": 100})
    assert execution.execute(intent(TradeSide.BUY, 3)).status == "filled"
    execution.set_fill_context(datetime(2026, 6, 15, 9, 40), {"SPY": 110})

    report = execution.execute(intent(TradeSide.SELL, 3))

    assert report.status == "filled"
    assert account.get_account_snapshot().cash == 1_030
    assert portfolio.get_portfolio_snapshot().positions == ()


def test_decision_after_a_pending_fill_sees_the_refreshed_portfolio():
    account, portfolio, execution = make_system()
    start = datetime(2026, 6, 15, 9, 30)
    bars = [
        MarketContext("SPY", start, "5m", 100, 101, 99, 100, 100),
        MarketContext("SPY", start + timedelta(minutes=5), "5m", 110, 111, 109, 110, 100),
        MarketContext("SPY", start + timedelta(minutes=10), "5m", 108, 109, 107, 108, 100),
    ]
    scheduler = NextBarExecutionScheduler(execution)
    planner = TargetToIntentPlanner()
    first, second, third = HistoricalReplay(bars)

    scheduler.begin_step(first)
    scheduler.queue([planner.plan(PortfolioTarget("SPY", target_quantity=2, source_strategy="trace"), portfolio.get_portfolio_snapshot())])
    assert scheduler.begin_step(second)[0].status == "filled"
    sell = planner.plan(PortfolioTarget("SPY", target_quantity=0, source_strategy="trace"), portfolio.get_portfolio_snapshot())
    assert sell is not None and sell.side == TradeSide.SELL
    scheduler.queue([sell])

    assert scheduler.begin_step(third)[0].side == TradeSide.SELL
    assert portfolio.get_portfolio_snapshot().positions == ()
    assert account.get_account_snapshot().cash == 996


def test_invalid_quantity_and_insufficient_buying_power_are_rejected_as_execution_reports():
    _, _, execution = make_system(cash=100)
    execution.set_fill_context(datetime(2026, 6, 15, 9, 35), {"SPY": 60})

    invalid = execution.execute(intent(TradeSide.BUY, 0))
    insufficient = execution.execute(intent(TradeSide.BUY, 2))

    assert isinstance(invalid, ExecutionReport)
    assert invalid.status == "rejected_invalid_quantity"
    assert insufficient.status == "rejected_insufficient_buying_power"
    assert insufficient.filled_quantity == 0


def test_explicit_costs_apply_each_side_and_minimum_fee_and_reconcile_cash():
    account, portfolio, _ = make_system()
    costs = ExecutionCosts(0.0035, 0.35, 2, 1)
    execution = SimulatedExecutionAdapter(account, portfolio, costs=costs)
    at = datetime(2026, 6, 15, 9, 35)
    execution.set_fill_context(at, {"SPY": 100})
    buy = execution.execute(intent(TradeSide.BUY, 2))
    assert buy.average_fill_price == pytest.approx(100.02)
    assert buy.commission == 0.35
    assert account.get_account_snapshot().total_equity == pytest.approx(1000 - 0.35 - buy.spread_cost - buy.slippage_cost)
    execution.set_fill_context(at + timedelta(minutes=1), {"SPY": 110})
    sell = execution.execute(intent(TradeSide.SELL, 2))
    assert sell.average_fill_price == pytest.approx(109.978)
    assert sell.commission == 0.35
    assert account.get_account_snapshot().cash == pytest.approx(1000 + 20 - 0.70
                                                                - buy.spread_cost - sell.spread_cost
                                                                - buy.slippage_cost - sell.slippage_cost)


def test_fee_can_make_an_otherwise_affordable_order_unaffordable():
    account, portfolio, _ = make_system(cash=100)
    execution = SimulatedExecutionAdapter(account, portfolio, costs=ExecutionCosts(0, 0.35, 0, 0))
    execution.set_fill_context(datetime(2026, 6, 15, 9, 35), {"SPY": 100})
    assert execution.execute(intent(TradeSide.BUY, 1)).status == "rejected_insufficient_buying_power"
    assert account.get_account_snapshot().cash == 100
    assert portfolio.get_portfolio_snapshot().positions == ()
