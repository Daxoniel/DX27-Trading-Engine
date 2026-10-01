from dx27.core.models.bot_signal import BotSignal, SignalDirection
from dx27.adapters.lean.signal_adapter import LeanSignalAdapter


def test_bot_signal_converts_to_lean_insight_spec():
    signal = BotSignal(
        bot_id="test_bot",
        symbol="SPY",
        direction=SignalDirection.LONG,
        confidence=0.80,
        horizon_days=30,
        reason=("integration_test",),
    )

    spec = LeanSignalAdapter.to_insight_spec(signal)

    assert spec.symbol == "SPY"
    assert spec.direction == "Up"
    assert spec.confidence == 0.80
    assert spec.horizon_days == 30