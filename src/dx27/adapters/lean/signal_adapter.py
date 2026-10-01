from dx27.core.models.bot_signal import BotSignal, SignalDirection
from dx27.adapters.lean.insight_spec import LeanInsightSpec


class LeanSignalAdapter:

    @staticmethod
    def to_lean_direction(signal: BotSignal) -> str:
        mapping = {
            SignalDirection.LONG: "Up",
            SignalDirection.SHORT: "Down",
            SignalDirection.HOLD: "Flat",
        }

        return mapping[signal.direction]

    @staticmethod
    def to_insight_spec(signal: BotSignal) -> LeanInsightSpec:
        return LeanInsightSpec(
            symbol=signal.symbol,
            direction=LeanSignalAdapter.to_lean_direction(signal),
            confidence=signal.confidence,
            horizon_days=signal.horizon_days,
        )