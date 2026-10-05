from datetime import datetime, timedelta

from dx27.application.historical_replay import HistoricalReplay
from dx27.adapters.simulated.account import SimulatedAccountAdapter
from dx27.adapters.simulated.execution import SimulatedExecutionAdapter
from dx27.adapters.simulated.portfolio import SimulatedPortfolioAdapter
from dx27.application.historical_replay import NextBarExecutionScheduler
from dx27.core.models.bot_signal import SignalDirection
from dx27.core.models.market_context import MarketContext
from dx27.core.models.portfolio_target import PortfolioTarget
from dx27.domains.intraday.bots.intraday_breakout import IntradayBreakoutBot
from dx27.domains.intraday.features.breakout_features import IntradayBreakoutFeatureCalculator
from dx27.execution_planning.target_to_intent import TargetToIntentPlanner


def test_tanyuan_orb_replay_signal_is_based_on_completed_prefix_only():
    start = datetime(2026, 10, 1, 9, 30)
    bars = [MarketContext("SPY", start + timedelta(minutes=5 * i), "5m", 100 + i, 101 + i, 99 + i, 100.5 + i, 100) for i in range(7)]
    replay = list(HistoricalReplay(bars))
    calculator = IntradayBreakoutFeatureCalculator(atr_period=2, adx_period=2)
    signal = IntradayBreakoutBot(adx_threshold=20).evaluate(replay[-1].context, calculator.calculate(replay[-1].history))
    assert signal is not None
    assert signal.direction == SignalDirection.LONG


def test_orb_signal_flows_to_next_bar_simulated_fill_and_portfolio():
    start = datetime(2026, 10, 1, 9, 30)
    bars = [MarketContext("SPY", start + timedelta(minutes=5 * i), "5m", 100 + i, 101 + i, 99 + i, 100.5 + i, 100) for i in range(8)]
    account, portfolio = SimulatedAccountAdapter(1_000), SimulatedPortfolioAdapter()
    account.attach_portfolio(portfolio)
    scheduler = NextBarExecutionScheduler(SimulatedExecutionAdapter(account, portfolio))
    calculator, bot, planner = IntradayBreakoutFeatureCalculator(2, 2), IntradayBreakoutBot(20), TargetToIntentPlanner()
    steps = list(HistoricalReplay(bars))
    for step in steps[:-1]:
        scheduler.begin_step(step)
        signal = bot.evaluate(step.context, calculator.calculate(step.history))
        if signal:
            intent = planner.plan(PortfolioTarget("SPY", 1, source_strategy=signal.bot_id, reason=signal.reason), portfolio.get_portfolio_snapshot())
            scheduler.queue([intent])
    reports = scheduler.begin_step(steps[-1])
    assert reports[0].timestamp == steps[-1].context.timestamp
    assert reports[0].average_fill_price == steps[-1].context.open
    assert portfolio.quantity_for("SPY") == 1
    assert account.get_account_snapshot().cash == 1_000 - steps[-1].context.open
