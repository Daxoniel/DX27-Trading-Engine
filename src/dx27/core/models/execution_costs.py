"""Explicit, deterministic costs for bar-based execution simulations."""

from dataclasses import dataclass
from math import isfinite

from dx27.core.models.trade_intent import TradeSide


@dataclass(frozen=True)
class ExecutionCosts:
    commission_per_share: float = 0.0035
    minimum_commission: float = 0.35
    spread_bps: float = 2.0
    slippage_bps: float = 1.0

    def __post_init__(self):
        values = (self.commission_per_share, self.minimum_commission,
                  self.spread_bps, self.slippage_bps)
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("execution costs must be finite and nonnegative")
        if self.spread_bps / 2 + self.slippage_bps >= 10_000:
            raise ValueError("execution friction must be below 100%")

    def commission(self, quantity: float) -> float:
        return max(self.minimum_commission, self.commission_per_share * quantity)

    def price(self, reference_price: float, side: TradeSide) -> float:
        direction = 1 if side == TradeSide.BUY else -1
        return reference_price * (1 + direction * (self.spread_bps / 2 + self.slippage_bps) / 10_000)
