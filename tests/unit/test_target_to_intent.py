from dx27.core.models.portfolio_snapshot import PortfolioSnapshot
from dx27.core.models.portfolio_target import PortfolioTarget
from dx27.core.models.position import Position
from dx27.core.models.trade_intent import TradeSide
from dx27.execution_planning.target_to_intent import TargetToIntentPlanner


def test_quantity_target_becomes_delta_buy_or_sell_intent():
    planner = TargetToIntentPlanner()
    portfolio = PortfolioSnapshot((Position("SPY", 2, 100, 105),))

    buy = planner.plan(PortfolioTarget("SPY", target_quantity=5, source_strategy="探员"), portfolio)
    sell = planner.plan(PortfolioTarget("SPY", target_quantity=0, source_strategy="探员"), portfolio)

    assert (buy.side, buy.quantity) == (TradeSide.BUY, 3)
    assert (sell.side, sell.quantity) == (TradeSide.SELL, 2)


def test_unchanged_target_needs_no_execution_intent():
    planner = TargetToIntentPlanner()
    portfolio = PortfolioSnapshot((Position("SPY", 2, 100, 105),))
    assert planner.plan(PortfolioTarget("SPY", target_quantity=2), portfolio) is None
