"""Credential-free fixed-host HTTP recorder acceptance; no external sockets."""

from email.message import Message
import io
import json
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler

import pytest

from dx27.adapters.alpaca import paper_probe, paper_recorder as module
from dx27.adapters.alpaca.paper_evidence import RecordedPaperTransport

AFTER, THROUGH = "2025-02-03T14:00:00Z", "2025-02-03T15:00:00Z"


class Response(io.BytesIO):
    def __init__(self, data=b"{}", *, status=200, headers=None, url=None):
        super().__init__(data)
        self.status, self.code, self.msg = status, status, "PRIVATE_VENDOR_MESSAGE"
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.url = url

    def geturl(self):
        return self.url

    def info(self):
        return self.headers


class Opener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        response = self.response or Response()
        if response.url is None:
            response.url = request.full_url
        return response


def recorder(opener=None, **changes):
    result = module.PaperHttpRecorder("PRIVATE_KEY", "PRIVATE_SECRET", **changes)
    result._opener = opener or Opener()
    return result


def test_fixed_paper_get_encoding_body_detachment_and_incomplete_recording():
    opener = Opener()
    client = recorder(opener)
    result = client.get("/v2/orders:by_client_order_id", {"client_order_id": "dx27h-a/b"})
    request, timeout = opener.calls[0]
    assert request.full_url == "https://paper-api.alpaca.markets/v2/orders:by_client_order_id?client_order_id=dx27h-a%2Fb"
    assert request.get_method() == "GET" and timeout == 10
    assert request.get_header("Apca-api-key-id") == "PRIVATE_KEY"
    result["mutated"] = True
    recording = client.recording()
    assert recording["entries"][0]["body"] == {}
    assert not recording["history_complete"] and not recording["coherent"]
    assert "PRIVATE_KEY" not in json.dumps(recording) and "PRIVATE_SECRET" not in json.dumps(recording)
    recording["entries"].clear()
    assert len(client.recording()["entries"]) == 1
    with pytest.raises(ValueError, match="HISTORY_NOT_ATTESTED"):
        RecordedPaperTransport(client.recording()["entries"], history_after=AFTER, through=THROUGH, history_complete=False)


@pytest.mark.parametrize("path,params", [
    ("https://api.alpaca.markets/v2/orders", {}), ("/v2/orders/123", {}),
    ("/v2/account?foo=bar", {}), ("/v2/account", {"redirect": "secret"}),
    ("/v2/orders", {"status": "open", "limit": True, "direction": "asc", "nested": False}),
    ("/v2/orders", {"status": "open", "limit": 501, "direction": "asc", "nested": False}),
    ("/v2/orders:by_client_order_id", {"client_order_id": "\r\nPRIVATE_SECRET"}),
    ("/v2/account/activities", {"page_token": "anything"}),
])
def test_query_allowlist_before_authenticated_call(path, params):
    client = recorder()
    with pytest.raises(module.PaperRecorderError):
        client.get(path, params)
    assert client.attempts == 0 and not client._opener.calls


@pytest.mark.parametrize("changes", [{"timeout": True}, {"timeout": float("nan")}, {"timeout": float("inf")},
                                    {"timeout": 0}, {"timeout": 61}, {"max_requests": True},
                                    {"max_requests": 0}, {"max_requests": 513}])
def test_invalid_resource_limits(changes):
    with pytest.raises(module.PaperRecorderError):
        recorder(**changes)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("probe", [False, True])
def test_default_opener_never_follows_redirect(monkeypatch, status, probe):
    calls = []
    def https_open(self, request):
        calls.append(request.full_url)
        return Response(status=status, headers={"Location": "https://api.alpaca.markets/private"}, url=request.full_url)
    monkeypatch.setattr(HTTPSHandler, "https_open", https_open)
    client = paper_probe.PaperReadOnlyClient("PRIVATE_KEY", "PRIVATE_SECRET") if probe else module.PaperHttpRecorder("PRIVATE_KEY", "PRIVATE_SECRET")
    with pytest.raises((module.PaperRecorderError, paper_probe.PaperProbeError)) as exc:
        client.get("/v2/account")
    assert calls == ["https://paper-api.alpaca.markets/v2/account"]
    assert "PRIVATE" not in str(exc.value) and "api.alpaca.markets/private" not in str(exc.value)


@pytest.mark.parametrize("data,headers", [
    (b'{"x":1,"x":2}', {}), (b'{"x":NaN}', {}), (b'{"x":1e999}', {}), (b"\xff", {}),
    (b"[", {}), (b"[]", {}), (b"{}", {"Content-Encoding": "gzip"}),
    (b"{}", {"Content-Type": "text/html"}), (b"{}", {"Content-Length": "262145"}),
    (b"{}", {"Content-Length": "-1"}), (b" " * 262145, {}),
    (b"{}", {"Content-Length": "100"}),
], ids=["duplicate-keys", "nan", "infinite-exponent", "invalid-utf8", "malformed-json",
         "wrong-shape", "gzip", "html", "oversized-length", "negative-length",
         "oversized-body", "truncated-length"])
def test_malformed_bounded_response_is_rejected(data, headers):
    # Replace rather than duplicate a Content-Type header in the fake.
    response = Response(data, headers={k: v for k, v in headers.items() if k != "Content-Type"})
    if "Content-Type" in headers:
        response.headers.replace_header("Content-Type", headers["Content-Type"])
    client = recorder(Opener(response))
    with pytest.raises(module.PaperRecorderError):
        client.get("/v2/account")
    assert not client.entries


@pytest.mark.parametrize("error", [
    HTTPError("https://paper-api.alpaca.markets/private", 401, "PRIVATE_SECRET", {}, io.BytesIO(b"PRIVATE_KEY")),
    URLError("PRIVATE_SECRET"), TimeoutError("PRIVATE_KEY"), IncompleteRead(b"PRIVATE_SECRET"),
])
def test_error_redaction_and_no_retry(error):
    opener = Opener(error=error)
    client = recorder(opener)
    with pytest.raises(module.PaperRecorderError) as exc:
        client.get("/v2/account")
    assert "PRIVATE" not in str(exc.value)
    assert len(opener.calls) == 1 and client.attempts == 1 and not client.entries


def test_changed_destination_and_request_budget():
    client = recorder(Opener(Response(url="https://api.alpaca.markets/v2/account")))
    with pytest.raises(module.PaperRecorderError, match="UNEXPECTED_PAPER_RESPONSE"):
        client.get("/v2/account")
    client = recorder(max_requests=1)
    client.get("/v2/account")
    with pytest.raises(module.PaperRecorderError, match="REQUEST_LIMIT"):
        client.get("/v2/account")
    assert len(client._opener.calls) == 1


class SampleOpener(Opener):
    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if "/v2/account/activities" in request.full_url:
            body = [{"activity_type": "FEE", "description": "PRIVATE_SECRET", "id": "PRIVATE_ID"}]
        elif any(path in request.full_url for path in ("/positions", "/orders")):
            body = [{"symbol": "PRIVATE_SYMBOL", "id": "PRIVATE_ID"}]
        else:
            body = dict(status="ACTIVE", currency="USD", account_number="PRIVATE_ACCOUNT", cash="123456789")
        return Response(json.dumps(body).encode(), url=request.full_url)


def test_minimized_sample_never_claims_complete_evidence():
    client = recorder(SampleOpener())
    result = module.sample_read_only(client, after=AFTER, through=THROUGH)
    encoded = json.dumps(result)
    assert result["sampling_complete"] and len(client.entries) == 5
    assert "PRIVATE" not in encoded and "123456789" not in encoded
    assert not result["evidence_complete"] and not result["snapshot_atomicity_verified"]
    assert not result["endpoints"]["activities"]["fee_order_attribution_verified"]
    assert not result["execution_enabled"] and not result["real_orders_sent"]
    assert "nested=false" in client._opener.calls[3][0].full_url


def test_failed_sample_stops_and_keeps_read_only_incomplete_status():
    client = recorder(Opener(error=URLError("PRIVATE_SECRET")))
    result = module.sample_read_only(client, after=AFTER, through=THROUGH)
    assert not result["sampling_complete"] and len(client._opener.calls) == 1
    assert result["endpoints"]["account"]["code"] == "PAPER_NETWORK_UNAVAILABLE"


def test_cli_private_recording_minimized_report_and_exclusive_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APCA_API_KEY_ID", "PRIVATE_KEY")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "PRIVATE_SECRET")
    monkeypatch.setattr(module, "build_opener", lambda *args: SampleOpener())
    report, raw = tmp_path / "report.json", tmp_path / "raw.json"
    args = ["--after", AFTER, "--through", THROUGH, "--report", str(report), "--recording", str(raw)]
    assert module.main(args) == 0
    assert "PRIVATE" not in capsys.readouterr().out
    assert "PRIVATE" not in report.read_text()
    assert "PRIVATE_ACCOUNT" in raw.read_text() and "PRIVATE_KEY" not in raw.read_text()
    assert module.main(args) == 1
    assert "PAPER_RECORDER_FAILED" in capsys.readouterr().out
    if __import__("os").name == "posix":
        assert raw.stat().st_mode & 0o777 == 0o600


def test_cli_missing_credentials_and_bad_window_never_connect(monkeypatch, capsys):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.setattr(module, "build_opener", lambda *args: pytest.fail("must not build client"))
    assert module.main(["--after", AFTER, "--through", THROUGH]) == 1
    assert module.main(["--after", THROUGH, "--through", AFTER]) == 1
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.parametrize("key,secret", [("", "x"), ("x", ""), ("x\r\ny", "z"), ("x", "z\ny")])
def test_invalid_credentials_fail_before_client_creation(key, secret, monkeypatch):
    monkeypatch.setattr(module, "build_opener", lambda *args: pytest.fail("must not build client"))
    with pytest.raises(module.PaperRecorderError, match="CREDENTIALS_REQUIRED"):
        module.PaperHttpRecorder(key, secret)


def test_paged_activity_query_uses_encoded_allowlisted_get():
    client = recorder(Opener(Response(b"[]")))
    params = dict(activity_types="FILL,FEE,CFEE", after=AFTER, until=THROUGH,
                  direction="asc", page_size=2, page_token="event/1")
    assert client.get("/v2/account/activities", params) == []
    assert "page_token=event%2F1" in client._opener.calls[0][0].full_url


def test_cli_network_failure_and_aliased_outputs_are_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APCA_API_KEY_ID", "PRIVATE_KEY")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "PRIVATE_SECRET")
    opener = Opener(error=URLError("PRIVATE_SECRET"))
    monkeypatch.setattr(module, "build_opener", lambda *args: opener)
    assert module.main(["--after", AFTER, "--through", THROUGH]) == 2
    assert "PRIVATE" not in capsys.readouterr().out and len(opener.calls) == 1
    path = str(tmp_path / "same.json")
    assert module.main(["--report", path, "--recording", path]) == 1
    assert not (tmp_path / "same.json").exists() and len(opener.calls) == 1
