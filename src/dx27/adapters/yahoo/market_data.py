import yfinance as yf


class YahooMarketDataAdapter:

    def get_bars(
        self,
        symbol: str,
        period: str = "30d",
        interval: str = "5m",
    ):
        data = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
        )

        if data.empty:
            raise ValueError(f"No market data returned for {symbol}")

        # yfinance may return MultiIndex columns such as:
        # ("Open", "SPY"), ("High", "SPY"), ...
        # Normalize them to:
        # Open, High, Low, Close, Volume
        if getattr(data.columns, "nlevels", 1) > 1:
            data.columns = data.columns.get_level_values(0)

        return data