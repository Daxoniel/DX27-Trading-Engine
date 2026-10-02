from dx27.core.interfaces.account import AccountPort
from dx27.core.models.account_snapshot import AccountSnapshot


class SimulatedAccountAdapter(AccountPort):
    def __init__(self, initial_cash: float):
        if initial_cash < 0:
            raise ValueError("initial_cash cannot be negative")
        self._cash = float(initial_cash)
        self._portfolio = None

    def attach_portfolio(self, portfolio) -> None:
        self._portfolio = portfolio

    def get_account_snapshot(self) -> AccountSnapshot:
        holdings_value = 0.0
        if self._portfolio is not None:
            holdings_value = sum(
                position.market_value
                for position in self._portfolio.get_portfolio_snapshot().positions
            )
        return AccountSnapshot(
            total_equity=self._cash + holdings_value,
            cash=self._cash,
            buying_power=self._cash,
        )

    def debit(self, amount: float) -> None:
        self._cash -= amount

    def credit(self, amount: float) -> None:
        self._cash += amount
