from dx27.core.models.trade_result import TradeResult


class IntradayTradeManager:

    def __init__(
        self,
        symbol: str,
        entry_time,
        entry_price: float,
        atr: float,
        quantity: float = 1.0,
        stop_atr: float = 1.0,
        target_atr: float = 2.0,
    ):
        self.symbol = symbol

        self.entry_time = entry_time
        self.entry_price = entry_price
        self.quantity = quantity

        self.stop_price = entry_price - atr * stop_atr
        self.target_price = entry_price + atr * target_atr

        self.closed = False

    def update(self, timestamp, bar):
        if self.closed:
            return None

        # 保守处理：
        # 同一根bar同时碰到止损和止盈时，先认为止损发生。
        if bar.low <= self.stop_price:
            return self._close(
                timestamp=timestamp,
                exit_price=self.stop_price,
                reason="stop_loss",
            )

        if bar.high >= self.target_price:
            return self._close(
                timestamp=timestamp,
                exit_price=self.target_price,
                reason="take_profit",
            )

        # 15:50 或之后，日内强制平仓
        if timestamp.hour > 15 or (
            timestamp.hour == 15 and timestamp.minute >= 50
        ):
            return self._close(
                timestamp=timestamp,
                exit_price=bar.close,
                reason="end_of_day",
            )

        return None

    def _close(self, timestamp, exit_price, reason):
        self.closed = True

        pnl = (
            exit_price - self.entry_price
        ) * self.quantity

        return_pct = (
            exit_price / self.entry_price - 1.0
        ) * 100.0

        return TradeResult(
            symbol=self.symbol,
            entry_time=self.entry_time,
            exit_time=timestamp,
            entry_price=self.entry_price,
            exit_price=exit_price,
            quantity=self.quantity,
            pnl=pnl,
            return_pct=return_pct,
            exit_reason=reason,
        )