import json
from urllib.error import HTTPError, URLError

import pytest

from dx27.adapters.intraday import account_probe as probe


def credentials(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "private-key-value")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "private-secret-value")


def test_missing_credentials_never_makes_network_calls(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.setattr(probe, "_get", lambda *a: pytest.fail("unexpected network"))
    assert probe.probe_paper_account()["status"] == "MISSING_CREDENTIALS"


def test_probe_uses_only_paper_get_endpoints_and_omits_ids_secrets_and_arbitrary_text(monkeypatch, tmp_path):
    credentials(monkeypatch)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            name = requests[-1].full_url.rsplit("/", 1)[-1]
            values = {"account": dict(status="ACTIVE", trading_blocked=False, account_blocked=False,
                                      id="private-account-id", account_number="123-private", secret="private-key-value"),
                      "clock": dict(timestamp="2026-10-14T09:00:00-04:00", is_open=False),
                      "positions": [dict(symbol="SPY", qty="1", asset_id="private-id")]}
            return json.dumps(values[name]).encode()

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert request.get_method() == "GET"
            assert request.full_url.startswith(probe.PAPER_BASE_URL + "/v2/")
            assert timeout == 15
            return Response()

    monkeypatch.setattr(probe, "build_opener", lambda handler: Opener())
    output = tmp_path / "p0.json"
    assert probe.main(["--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["checks"]["positions"]["position_count"] == 1
    assert result["automatic_orders_enabled"] is False
    assert result["realtime_data_verified"] is False
    assert len(requests) == 3
    assert "private" not in output.read_text()


@pytest.mark.parametrize("error,status", [(HTTPError("url", 401, "private-secret-value", {}, None), "HTTP_ERROR"),
                                         (URLError("private-key-value"), "CONNECTION_ERROR"),
                                         (ValueError("private-key-value"), "INVALID_RESPONSE")])
def test_errors_never_echo_provider_bodies_or_exception_messages(monkeypatch, error, status):
    credentials(monkeypatch)

    def fail(*args):
        raise error

    monkeypatch.setattr(probe, "_get", fail)
    result = probe.probe_paper_account()
    assert result["status"] == "NOT_VERIFIED"
    assert {c["status"] for c in result["checks"].values()} == {status}
    assert "private" not in json.dumps(result)


def test_unexpected_schema_does_not_pass_and_redirects_are_not_followed(monkeypatch):
    credentials(monkeypatch)
    monkeypatch.setattr(probe, "_get", lambda *a: {"private-key-value": "oops"})
    assert probe.probe_paper_account()["status"] == "NOT_VERIFIED"
    assert probe._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example") is None


@pytest.mark.parametrize("value", [None, 7, [], {}])
def test_malformed_clock_timestamp_is_an_invalid_response(value):
    with pytest.raises(ValueError):
        probe._safe_observation("clock", {"is_open": False, "timestamp": value})
