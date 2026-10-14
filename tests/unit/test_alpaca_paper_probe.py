"""Offline acceptance tests: no real API credentials or external network."""

import io
import json
from urllib.error import HTTPError

import pytest

from dx27.adapters.alpaca import paper_probe


class FakeClient:
    def __init__(self):
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path == "/v2/account":
            return {
                "status": "ACTIVE",
                "trading_blocked": False,
                "account_blocked": False,
                "account_number": "DO_NOT_PUBLISH",
                "buying_power": "999999",
            }
        if path == "/v2/clock":
            return {
                "is_open": False,
                "next_open": "2026-10-15T09:30:00-04:00",
                "next_close": "2026-10-15T16:00:00-04:00",
            }
        return {"symbol": path.rsplit("/", 1)[1], "status": "active",
                "tradable": True, "fractionable": True}


class FakeResponse:
    def __init__(self, data):
        self.data = io.BytesIO(json.dumps(data).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.data.read(size)


def test_sanitized_status_never_returns_account_identity():
    client = FakeClient()
    result = paper_probe.run_probe(client, ("SPY", "QQQ", "IWM"))
    assert result["environment"] == "ALPACA_PAPER_ONLY"
    assert result["connected"] is True
    assert result["execution_enabled"] is False
    assert result["market_data_feed_verified"] is False
    assert result["assets"]["QQQ"]["tradable"]
    assert "DO_NOT_PUBLISH" not in json.dumps(result)
    assert "999999" not in json.dumps(result)
    assert client.paths == ["/v2/account", "/v2/clock", "/v2/assets/SPY",
                            "/v2/assets/QQQ", "/v2/assets/IWM"]


@pytest.mark.parametrize("symbols", ["", "SPY,", "SPY,SPY", "SPY,/v2/orders",
                                      "spy", "SPY;QQQ", "A"*11])
def test_reject_bad_symbols(symbols):
    with pytest.raises(paper_probe.PaperProbeError):
        paper_probe.parse_symbols(symbols)


def test_fixed_paper_host_read_only_and_credentials_not_echoed(monkeypatch):
    captured = []

    def fake_open(request, *, timeout):
        captured.append((request.full_url, request.get_method(), timeout,
                         request.get_header("Apca-api-key-id")))
        return FakeResponse({"status": "ACTIVE"})

    monkeypatch.setattr(paper_probe, "urlopen", fake_open)
    client = paper_probe.PaperReadOnlyClient("PRIVATE_KEY", "PRIVATE_SECRET")
    assert client.get("/v2/account") == {"status": "ACTIVE"}
    assert captured[0][:3] == ("https://paper-api.alpaca.markets/v2/account",
                               "GET", 10.0)
    assert captured[0][3] == "PRIVATE_KEY"
    with pytest.raises(paper_probe.PaperProbeError):
        client.get("/v2/orders")
    with pytest.raises(paper_probe.PaperProbeError):
        client.get("https://api.alpaca.markets/v2/account")
    assert len(captured) == 1


def test_http_errors_hide_response_body_and_keys(monkeypatch):
    def fail(request, *, timeout):
        raise HTTPError(request.full_url, 403, "PRIVATE_SECRET",
                        {}, io.BytesIO(b"PRIVATE_KEY"))

    monkeypatch.setattr(paper_probe, "urlopen", fail)
    client = paper_probe.PaperReadOnlyClient("PRIVATE_KEY", "PRIVATE_SECRET")
    with pytest.raises(paper_probe.PaperProbeError) as exc:
        client.get("/v2/clock")
    assert "403" in str(exc.value)
    assert "PRIVATE_KEY" not in str(exc.value)
    assert "PRIVATE_SECRET" not in str(exc.value)


def test_cli_no_keys_exits_without_traffic(monkeypatch, capsys):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert paper_probe.main([]) == 1
    output = capsys.readouterr()
    assert "PAPER" in output.err
    assert not output.out


def test_fail_closed_on_unexpected_response():
    class BadClient(FakeClient):
        def get(self, path):
            if path == "/v2/clock":
                return {"is_open": "false"}
            return super().get(path)

    with pytest.raises(paper_probe.PaperProbeError):
        paper_probe.run_probe(BadClient(), ("SPY",))
