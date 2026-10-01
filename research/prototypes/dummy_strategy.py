from dx27.core.models.bot_signal import BotSignal, SignalDirection
from dx27.core.interfaces.strategy import Strategy


class DummyStrategy(Strategy):

    def evaluate(self, context) -> BotSignal:
        return BotSignal(
            bot_id="dummy_strategy",
            symbol="SPY",
            direction=SignalDirection.LONG,
            confidence=0.80,
            horizon_days=30,
            reason=("dummy_test_signal",),
        )