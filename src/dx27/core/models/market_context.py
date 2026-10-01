from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    timestamp: datetime
    timeframe: str

    open: float
    high: float
    low: float
    close: float
    volume: float