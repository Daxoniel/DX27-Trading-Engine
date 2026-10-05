from datetime import time
from zoneinfo import ZoneInfo

from dx27.core.interfaces.intraday_bot import IntradayBot
from dx27.core.models.bot_signal import BotSignal, SignalDirection


class IntradayBreakoutBot(IntradayBot):
    """探员, DX27's single intraday Opening Range Breakout bot."""

    bot_id = "tanyuan_orb"
    display_name = "探员"

    def __init__(self, adx_threshold: float = 25.0):
        self.adx_threshold = adx_threshold
        self.last_signal_date = None
        self._new_york = ZoneInfo("America/New_York")

    def evaluate(self, context, features) -> BotSignal | None:
        local = context.timestamp.replace(tzinfo=self._new_york) if context.timestamp.tzinfo is None else context.timestamp.astimezone(self._new_york)
        if not time(9, 30) <= local.time() < time(16, 0):
            return None
        if not features.opening_range_ready or not features.indicators_ready:
            return None
        if features.adx is None or features.adx < self.adx_threshold:
            return None
        if self.last_signal_date == local.date():
            return None
        if context.close > features.opening_range_high:
            direction = SignalDirection.LONG
            breakout_reason = "close_above_opening_range_high"
        elif context.close < features.opening_range_low:
            direction = SignalDirection.SHORT
            breakout_reason = "close_below_opening_range_low"
        else:
            return None
        self.last_signal_date = local.date()
        return BotSignal(self.bot_id, context.symbol, direction, 0.70, 1, (
            breakout_reason,
            f"adx={features.adx:.2f} >= threshold={self.adx_threshold:.2f}",
            f"opening_range=({features.opening_range_low:.4f}, {features.opening_range_high:.4f})",
        ))
