from dx27.adapters.yahoo.market_data import YahooMarketDataAdapter
from dx27.core.models.market_context import MarketContext
from dx27.features.intraday_breakout_features import (
    IntradayBreakoutFeatureCalculator,
)
from dx27.strategies.plugins.intraday.intraday_breakout import (
    IntradayBreakoutBot,
)
from dx27.strategies.plugins.intraday.trade_manager import (
    IntradayTradeManager,
)


class SimpleBar:

    def __init__(
        self,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ):
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def main():
    symbol = "SPY"

    data_adapter = YahooMarketDataAdapter()
    feature_calculator = IntradayBreakoutFeatureCalculator()
    bot = IntradayBreakoutBot()

    data = data_adapter.get_bars(
        symbol=symbol,
        period="30d",
        interval="5m",
    )

    print(f"Loaded {len(data)} bars for {symbol}")
    print()

    bars = []
    trades = []

    current_date = None
    active_trade = None

    for timestamp, row in data.iterrows():

        bar_date = timestamp.date()

        # 新交易日
        if current_date != bar_date:
            bars = []
            current_date = bar_date

        bar = SimpleBar(
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]),
        )

        # =========================
        # 1. 先管理已有持仓
        # =========================
        if active_trade is not None:
            result = active_trade.update(
                timestamp=timestamp.to_pydatetime(),
                bar=bar,
            )

            if result is not None:
                trades.append(result)
                active_trade = None

        # =========================
        # 2. 更新 rolling bars
        # =========================
        bars.append(bar)

        if len(bars) < 21:
            continue

        if len(bars) > 21:
            bars.pop(0)

        # =========================
        # 3. 已经有持仓时不再开新仓
        # =========================
        if active_trade is not None:
            continue

        features = feature_calculator.calculate(bars)

        context = MarketContext(
            symbol=symbol,
            timestamp=timestamp.to_pydatetime(),
            timeframe="5m",
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

        signal = bot.evaluate(
            context=context,
            features=features,
        )

        if signal is None:
            continue

        # =========================
        # 4. 创建新交易
        # =========================
        active_trade = IntradayTradeManager(
            symbol=symbol,
            entry_time=context.timestamp,
            entry_price=context.close,
            atr=features.atr_14,
            quantity=1.0,
            stop_atr=1.0,
            target_atr=2.0,
        )

        print(
            f"ENTRY {context.timestamp} "
            f"{symbol} "
            f"price={context.close:.2f} "
            f"ATR={features.atr_14:.2f} "
            f"stop={active_trade.stop_price:.2f} "
            f"target={active_trade.target_price:.2f}"
        )

    # =========================
    # 输出所有已完成交易
    # =========================
    print()
    print(f"Completed trades: {len(trades)}")
    print()

    for trade in trades:
        print(
            f"{trade.entry_time} -> {trade.exit_time} "
            f"{trade.symbol} "
            f"entry={trade.entry_price:.2f} "
            f"exit={trade.exit_price:.2f} "
            f"PnL={trade.pnl:.2f} "
            f"return={trade.return_pct:.3f}% "
            f"reason={trade.exit_reason}"
        )

    # =========================
    # 汇总统计
    # =========================
    if not trades:
        print("No completed trades.")
        return

    wins = [trade for trade in trades if trade.pnl > 0]
    losses = [trade for trade in trades if trade.pnl < 0]

    total_pnl = sum(trade.pnl for trade in trades)
    average_pnl = total_pnl / len(trades)

    win_rate = len(wins) / len(trades) * 100.0

    gross_profit = sum(trade.pnl for trade in wins)
    gross_loss = abs(sum(trade.pnl for trade in losses))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf")

    print()
    print("=== DX27 Intraday Breakout v0.1 ===")
    print(f"Trades:        {len(trades)}")
    print(f"Wins:          {len(wins)}")
    print(f"Losses:        {len(losses)}")
    print(f"Win rate:      {win_rate:.2f}%")
    print(f"Total PnL:     {total_pnl:.2f}")
    print(f"Average PnL:   {average_pnl:.2f}")
    print(f"Profit factor: {profit_factor:.2f}")


if __name__ == "__main__":
    main()