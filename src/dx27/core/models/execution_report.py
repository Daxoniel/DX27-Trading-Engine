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

    commission: float = 0.0
    reference_price: float | None = None
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
