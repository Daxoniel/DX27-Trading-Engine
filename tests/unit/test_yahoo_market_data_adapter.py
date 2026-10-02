import pytest

pd = pytest.importorskip("pandas")

from dx27.adapters.yahoo.market_data import YahooMarketDataAdapter


def test_yahoo_adapter_normalizes_timezone_session_and_order(monkeypatch):
    data = pd.DataFrame(
        {"Open": [3, 1, 2], "High": [3, 1, 2], "Low": [3, 1, 2], "Close": [3, 1, 2], "Volume": [3, 1, 2]},
        index=pd.to_datetime(["2026-06-15T20:00:00Z", "2026-06-15T13:30:00Z", "2026-06-15T14:30:00Z"]),
    )
    monkeypatch.setattr(YahooMarketDataAdapter, "_download", staticmethod(lambda **_: data))

    result = YahooMarketDataAdapter().get_bars("SPY", period="5d", interval="5m")

    assert str(result.index.tz) == "America/New_York"
    assert list(result.index.hour) == [9, 10]
    assert list(result["Open"]) == [1, 2]


def test_yahoo_adapter_supports_a_single_trading_date(monkeypatch):
    data = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]}, index=pd.to_datetime(["2026-06-15T13:30:00Z"]))
    received = {}

    def download(**kwargs):
        received.update(kwargs)
        return data

    monkeypatch.setattr(YahooMarketDataAdapter, "_download", staticmethod(download))
    YahooMarketDataAdapter().get_bars("SPY", trading_date="2026-06-15")

    assert received["start"] == "2026-06-15"
    assert received["end"] == "2026-06-16"
