from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioTarget:
    symbol: str
    target_quantity: float | None = None
    target_notional: float | None = None

    source_strategy: str = ""
    reason: tuple[str, ...] = ()