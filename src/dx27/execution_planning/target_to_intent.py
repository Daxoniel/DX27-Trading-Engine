from dx27.core.models.portfolio_snapshot import PortfolioSnapshot
from dx27.core.models.portfolio_target import PortfolioTarget
from dx27.core.models.trade_intent import TradeIntent, TradeSide


class TargetToIntentPlanner:
    """Plan one whole-quantity market intent for a quantity-based target."""

    def plan(self, target: PortfolioTarget, portfolio: PortfolioSnapshot) -> TradeIntent | None:
        if target.target_quantity is None:
            raise ValueError("Phase 1 planning requires target_quantity")
        current_quantity = next(
            (position.quantity for position in portfolio.positions if position.symbol == target.symbol),
            0.0,
        )
        delta = target.target_quantity - current_quantity
        if delta == 0:
            return None
        return TradeIntent(
            strategy_id=target.source_strategy,
            symbol=target.symbol,
            side=TradeSide.BUY if delta > 0 else TradeSide.SELL,
            quantity=abs(delta),
            reason=target.reason,
        )
