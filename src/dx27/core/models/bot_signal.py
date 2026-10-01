from dataclasses import dataclass
from enum import Enum


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    HOLD = "hold"


@dataclass(frozen=True)
class BotSignal:
    bot_id: str
    symbol: str
    direction: SignalDirection
    confidence: float
    horizon_days: int
    reason: tuple[str, ...] = ()