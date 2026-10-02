from dx27.core.interfaces.portfolio import PortfolioPort
from dx27.core.models.portfolio_snapshot import PortfolioSnapshot
from dx27.core.models.position import Position


class SimulatedPortfolioAdapter(PortfolioPort):
    def __init__(self):
        self._positions: dict[str, Position] = {}

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(positions=tuple(self._positions.values()))

    def update_market_price(self, symbol: str, price: float) -> None:
        position = self._positions.get(symbol)
        if position is not None:
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=position.quantity,
                average_price=position.average_price,
                market_price=price,
            )

    def quantity_for(self, symbol: str) -> float:
        position = self._positions.get(symbol)
        return 0.0 if position is None else position.quantity

    def buy(self, symbol: str, quantity: float, price: float) -> None:
        old = self._positions.get(symbol)
        old_quantity = 0.0 if old is None else old.quantity
        old_cost = 0.0 if old is None else old.average_price * old_quantity
        new_quantity = old_quantity + quantity
        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=new_quantity,
            average_price=(old_cost + quantity * price) / new_quantity,
            market_price=price,
        )

    def sell(self, symbol: str, quantity: float, price: float) -> None:
        old = self._positions[symbol]
        remaining = old.quantity - quantity
        if remaining == 0:
            del self._positions[symbol]
            return
        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=remaining,
            average_price=old.average_price,
            market_price=price,
        )
