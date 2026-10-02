from datetime import datetime

from dx27.core.interfaces.execution import ExecutionPort
from dx27.core.models.execution_report import ExecutionReport
from dx27.core.models.trade_intent import TradeIntent, TradeSide


class SimulatedExecutionAdapter(ExecutionPort):
    """Fill whole market orders at the configured next completed bar's open."""

    def __init__(self, account, portfolio, slippage_bps: float = 0.0):
        if slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        self._account = account
        self._portfolio = portfolio
        self._slippage = slippage_bps / 10_000
        self._timestamp: datetime | None = None
        self._open_prices: dict[str, float] = {}

    def set_fill_context(self, timestamp: datetime, open_prices: dict[str, float]) -> None:
        """Set the next eligible bar-open prices before executing queued intents."""
        self._timestamp = timestamp
        self._open_prices = dict(open_prices)
        for symbol, price in self._open_prices.items():
            self._portfolio.update_market_price(symbol, price)

    def execute(self, intent: TradeIntent) -> ExecutionReport:
        timestamp = self._timestamp or datetime.min
        quantity = intent.quantity
        if quantity is None or quantity <= 0:
            return self._rejected(intent, timestamp, "rejected_invalid_quantity")
        if intent.symbol not in self._open_prices:
            return self._rejected(intent, timestamp, "rejected_missing_fill_price")

        open_price = self._open_prices[intent.symbol]
        price = open_price * (1 + self._slippage if intent.side == TradeSide.BUY else 1 - self._slippage)
        notional = quantity * price
        if intent.side == TradeSide.BUY:
            if notional > self._account.get_account_snapshot().buying_power:
                return self._rejected(intent, timestamp, "rejected_insufficient_buying_power")
            self._account.debit(notional)
            self._portfolio.buy(intent.symbol, quantity, price)
        elif intent.side == TradeSide.SELL:
            if quantity > self._portfolio.quantity_for(intent.symbol):
                return self._rejected(intent, timestamp, "rejected_insufficient_position")
            self._account.credit(notional)
            self._portfolio.sell(intent.symbol, quantity, price)
        else:
            return self._rejected(intent, timestamp, "rejected_invalid_side")

        return ExecutionReport(intent.symbol, intent.side, quantity, quantity, price, timestamp, "filled")

    def _rejected(self, intent: TradeIntent, timestamp: datetime, status: str) -> ExecutionReport:
        return ExecutionReport(intent.symbol, intent.side, intent.quantity or 0.0, 0.0, 0.0, timestamp, status)
