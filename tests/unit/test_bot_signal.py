from dx27.core.models.bot_signal import BotSignal, SignalDirection
from dx27.adapters.lean.signal_adapter import LeanSignalAdapter


def make_signal(direction: SignalDirection) -> BotSignal:
    return BotSignal(
        bot_id="test_bot",
        symbol="SPY",
        direction=direction,
        confidence=0.8,
        horizon_days=30,
        reason=("sandbox_test",),
    )


def test_long_signal_maps_to_lean_up():
    assert LeanSignalAdapter.to_lean_direction(
        make_signal(SignalDirection.LONG)
    ) == "Up"


def test_short_signal_maps_to_lean_down():
    assert LeanSignalAdapter.to_lean_direction(
        make_signal(SignalDirection.SHORT)
    ) == "Down"


def test_hold_signal_maps_to_lean_flat():
    assert LeanSignalAdapter.to_lean_direction(
        make_signal(SignalDirection.HOLD)
    ) == "Flat"


def test_bot_signal_keeps_metadata():
    signal = make_signal(SignalDirection.LONG)

    assert signal.bot_id == "test_bot"
    assert signal.symbol == "SPY"
    assert signal.confidence == 0.8
    assert signal.horizon_days == 30
    assert signal.reason == ("sandbox_test",)