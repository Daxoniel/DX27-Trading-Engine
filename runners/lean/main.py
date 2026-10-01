from AlgorithmImports import *

from dx27.core.models.market_context import MarketContext
from dx27.features.intraday_breakout_features import (
    IntradayBreakoutFeatureCalculator,
)
from dx27.strategies.plugins.intraday.intraday_breakout import (
    IntradayBreakoutBot,
)
from dx27.core.models.bot_signal import SignalDirection


class DX27IntradayBreakoutRunner(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2025, 1, 2)
        self.set_end_date(2025, 1, 31)
        self.set_cash(100000)

        self.symbol = self.add_equity(
            "SPY",
            Resolution.MINUTE
        ).symbol

        self.consolidator = TradeBarConsolidator(timedelta(minutes=5))
        self.consolidator.data_consolidated += self.on_five_minute_bar

        self.subscription_manager.add_consolidator(
            self.symbol,
            self.consolidator
        )

        self.bars = []

        self.feature_calculator = IntradayBreakoutFeatureCalculator()
        self.bot = IntradayBreakoutBot()

    def on_five_minute_bar(self, sender, bar):
        self.bars.append(bar)

        # 我们只需要当前bar + 前20根历史bar
        if len(self.bars) < 21:
            return

        # 防止列表无限增长
        if len(self.bars) > 21:
            self.bars.pop(0)

        features = self.feature_calculator.calculate(self.bars)

        context = MarketContext(
            symbol=str(self.symbol.value),
            timestamp=bar.end_time,
            timeframe="5m",
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )

        signal = self.bot.evaluate(
            context=context,
            features=features,
        )

        if signal is None:
            return

        if signal.direction == SignalDirection.LONG:
            self.debug(
                f"{bar.end_time} DX27 LONG "
                f"{signal.symbol} "
                f"close={bar.close}"
            )