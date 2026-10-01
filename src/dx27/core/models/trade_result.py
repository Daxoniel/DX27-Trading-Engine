from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradeResult:
    symbol: str

    entry_time: datetime
    exit_time: datetime

    entry_price: float
    exit_price: float

    quantity: float
    pnl: float
    return_pct: float

    exit_reason: str