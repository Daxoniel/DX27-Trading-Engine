import pytest

from dx27.adapters.yahoo.market_data import YahooMarketDataAdapter


@pytest.mark.integration
@pytest.mark.network
def test_yahoo_returns_intraday_data():
    adapter = YahooMarketDataAdapter()

    data = adapter.get_bars(
        symbol="SPY",
        period="5d",
        interval="5m",
    )

    assert len(data) > 0
