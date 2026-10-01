from dataclasses import dataclass
from datetime import datetime

from dx27.core.models.trade_intent import TradeSide


@dataclass(frozen=True)
class ExecutionReport:
    symbol: str
    side: TradeSide

    requested_quantity: float
    filled_quantity: float
    average_fill_price: float

    timestamp: datetime
    status: str