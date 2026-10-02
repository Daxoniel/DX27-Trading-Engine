from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


class YahooMarketDataAdapter:

    session_timezone = ZoneInfo("America/New_York")
    session_open = time(9, 30)
    session_close = time(16, 0)

    @staticmethod
    def _download(**kwargs):
        import yfinance as yf

        return yf.download(**kwargs)

    def get_bars(
        self,
        symbol: str,
        period: str | None = "30d",
        interval: str = "5m",
        start: datetime | date | str | None = None,
        end: datetime | date | str | None = None,
        trading_date: date | str | None = None,
    ):
        """Return regular-session OHLCV bars ordered in New York time.

        Bar timestamps are treated as bar-start timestamps.  Yahoo does not
        supply an exchange-calendar abstraction here, so normal-session hours
        (09:30 <= timestamp < 16:00 America/New_York) are the only filter.
        Early-close sessions are not handled specially.
        """
        if trading_date is not None and (start is not None or end is not None):
            raise ValueError("trading_date cannot be combined with start or end")
        import pandas as pd

        download_args = {
            "tickers": symbol,
            "interval": interval,
            "auto_adjust": False,
            "progress": False,
        }
        if trading_date is not None:
            day = pd.Timestamp(trading_date).date()
            download_args["start"] = day.isoformat()
            download_args["end"] = (day + timedelta(days=1)).isoformat()
        elif start is not None or end is not None:
            download_args["start"] = start
            download_args["end"] = end
        else:
            download_args["period"] = period

        data = self._download(
            **download_args,
        )

        if data.empty:
            raise ValueError(f"No market data returned for {symbol}")

        # yfinance may return MultiIndex columns such as:
        # ("Open", "SPY"), ("High", "SPY"), ...
        # Normalize them to:
        # Open, High, Low, Close, Volume
        if getattr(data.columns, "nlevels", 1) > 1:
            data.columns = data.columns.get_level_values(0)

        index = pd.DatetimeIndex(data.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        data.index = index.tz_convert(self.session_timezone)
        data = data.sort_index(kind="stable")

        session_mask = (
            (data.index.dayofweek < 5)
            & (data.index.time >= self.session_open)
            & (data.index.time < self.session_close)
        )
        return data.loc[session_mask]
