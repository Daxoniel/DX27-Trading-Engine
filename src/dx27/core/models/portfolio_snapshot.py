from dataclasses import dataclass

from dx27.core.models.position import Position


@dataclass(frozen=True)
class PortfolioSnapshot:
    positions: tuple[Position, ...]