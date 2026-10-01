from dataclasses import dataclass


@dataclass(frozen=True)
class AccountSnapshot:
    total_equity: float
    cash: float
    buying_power: float