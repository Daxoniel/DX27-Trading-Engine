from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    average_price: float
    market_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price