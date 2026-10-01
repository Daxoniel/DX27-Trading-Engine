from dx27.core.models.bot_signal import BotSignal, SignalDirection
from dx27.domains.intraday.rules.breakout_rule import BreakoutRule
from dx27.domains.intraday.rules.volume_confirmation_rule import (
    VolumeConfirmationRule,
)


class IntradayBreakoutBot:

    def __init__(self):
        self.breakout_rule = BreakoutRule()
        self.volume_rule = VolumeConfirmationRule()

        # v0.1:
        # 每个交易日最多产生一次 LONG 信号
        self.last_signal_date = None

    def evaluate(self, context, features) -> BotSignal | None:
        breakout = self.breakout_rule.evaluate(
            context=context,
            features=features,
        )

        volume = self.volume_rule.evaluate(
            context=context,
            features=features,
        )

        # 没突破，不交易
        if not breakout.triggered:
            return None

        # 没有成交量确认，不交易
        if not volume.triggered:
            return None

        signal_date = context.timestamp.date()

        # 同一天已经产生过信号，不重复发
        if self.last_signal_date == signal_date:
            return None

        self.last_signal_date = signal_date

        return BotSignal(
            bot_id="intraday_breakout_v0_1",
            symbol=context.symbol,
            direction=SignalDirection.LONG,
            confidence=0.70,
            horizon_days=1,
            reason=(
                breakout.reason,
                volume.reason,
            ),
        )