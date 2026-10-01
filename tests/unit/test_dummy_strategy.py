from dx27.core.models.bot_signal import SignalDirection
from dx27.strategies.plugins.dummy_strategy import DummyStrategy


def test_dummy_strategy_emits_long_signal():
    strategy = DummyStrategy()

    signal = strategy.evaluate(context=None)

    assert signal.bot_id == "dummy_strategy"
    assert signal.symbol == "SPY"
    assert signal.direction == SignalDirection.LONG
    assert signal.confidence == 0.80
    assert signal.horizon_days == 30