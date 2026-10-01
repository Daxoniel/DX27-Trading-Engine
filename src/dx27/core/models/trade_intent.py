from dataclasses import dataclass
from enum import Enum


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class TradeIntent:
    strategy_id: str
    symbol: str
    side: TradeSide

    quantity: float | None = None
    notional: float | None = None

    reason: tuple[str, ...] = ()