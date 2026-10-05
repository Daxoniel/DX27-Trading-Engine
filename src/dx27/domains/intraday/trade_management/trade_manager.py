from dx27.core.models.trade_result import TradeResult
from zoneinfo import ZoneInfo


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
        direction: str = "long",
    ):
        self.symbol = symbol

        self.entry_time = entry_time
        self.entry_price = entry_price
        self.quantity = quantity

        if direction not in {"long", "short"}:
            raise ValueError("direction must be 'long' or 'short'")
        self.direction = direction
        self._new_york = ZoneInfo("America/New_York")
        self.stop_price = entry_price - atr * stop_atr if direction == "long" else entry_price + atr * stop_atr
        self.target_price = entry_price + atr * target_atr if direction == "long" else entry_price - atr * target_atr

        self.closed = False

    def update(self, timestamp, bar):
        if self.closed:
            return None

        # A position filled at a bar open is evaluated against that completed
        # bar's high/low.  When both levels are touched, conservatively select
        # the stop before the target.
        stop_touched = bar.low <= self.stop_price if self.direction == "long" else bar.high >= self.stop_price
        target_touched = bar.high >= self.target_price if self.direction == "long" else bar.low <= self.target_price
        if stop_touched:
            return self._close(
                timestamp=timestamp,
                exit_price=self.stop_price,
                reason="stop_loss",
            )

        if target_touched:
            return self._close(
                timestamp=timestamp,
                exit_price=self.target_price,
                reason="take_profit",
            )

        return None

    def end_of_day_exit_due(self, timestamp) -> bool:
        """Return whether a completed bar should schedule a next-open exit.

        Bar timestamps are interval-start timestamps. A true result does not
        itself create a fill: the caller must route a flat portfolio target
        through execution planning and the next-bar execution scheduler.
        """
        local = timestamp.replace(tzinfo=self._new_york) if timestamp.tzinfo is None else timestamp.astimezone(self._new_york)
        return local.hour > 15 or (
            local.hour == 15 and local.minute >= 50
        )

    def _close(self, timestamp, exit_price, reason):
        self.closed = True

        pnl = (exit_price - self.entry_price) * self.quantity
        if self.direction == "short":
            pnl = -pnl

        return_pct = (exit_price / self.entry_price - 1.0) * 100.0
        if self.direction == "short":
            return_pct = -return_pct

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
