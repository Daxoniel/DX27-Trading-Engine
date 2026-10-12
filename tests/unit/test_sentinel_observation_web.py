"""The local browser surface refreshes explicitly and never exposes files."""

from contextlib import contextmanager
import errno
from http.client import HTTPConnection
import json
import socket
from threading import Thread

import pytest

from dx27.adapters.sentinel import observation_web as web


class FakeService:
    def __init__(self):
        self.refresh_calls = 0
        self.latest_calls = 0
        self.failure = None
        self.report = {
            "report_id": "synthetic-report-1",
            "generated_at": "2026-10-12T09:00:00+00:00",
            "html": "<!doctype html><h1>Synthetic saved report</h1>",
            "status": "SYNTHETIC",
        }

    def refresh(self):
        self.refresh_calls += 1
        if self.failure:
            raise self.failure
        self.report = {**self.report, "report_id": "synthetic-report-2"}
        return self.report

    def latest(self):
        self.latest_calls += 1
        return self.report


@contextmanager
def running_server(tmp_path, service):
    server = web.create_server(
        tmp_path / "isolated-research",
        tmp_path / "protocol.json",
        0,
        service_factory=lambda root, protocol: service,
    )
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def live(tmp_path):
    service = FakeService()
    with running_server(tmp_path, service) as server:
        yield server, service


def request(server, method="GET", path="/", body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    request_headers = dict(headers or {})
    if method == "POST" and "Origin" not in request_headers:
        request_headers["Origin"] = f"http://127.0.0.1:{server.server_port}"
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode("utf-8")
    finally:
        connection.close()


def test_opening_page_returns_shell_without_collecting(live):
    server, service = live
    status, headers, body = request(server)

    assert status == 200
    assert service.refresh_calls == 0
    assert service.latest_calls == 0
    assert "正在更新" in body
    assert "Synthetic saved report" not in body
    assert 'fetch("/api/latest"' in body
    assert body.count('fetch("/api/refresh"') == 1
    assert 'method: "POST"' in body
    assert "loadSaved().finally(refresh)" in body
    assert 'sandbox="allow-popups allow-popups-to-escape-sandbox"' in body
    assert "allow-scripts" not in body
    assert "textContent" in body
    assert "innerHTML" not in body
    assert 'frame.srcdoc = \'<base target="_blank">\'' in body
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Access-Control-Allow-Origin" not in headers


def test_latest_reads_saved_report_without_refresh(live):
    server, service = live
    status, headers, body = request(server, path="/api/latest")

    assert status == 200
    assert json.loads(body) == service.report
    assert service.refresh_calls == 0
    assert service.latest_calls == 1
    assert headers["Cache-Control"] == "no-store"


def test_latest_before_first_report_is_readable(live):
    server, service = live
    service.report = None
    status, _, body = request(server, path="/api/latest")

    assert status == 404
    assert json.loads(body)["report"] is None
    assert "No saved research report" in json.loads(body)["error"]
    assert service.refresh_calls == 0


@pytest.mark.parametrize("body", [None, b"", b"{}", b" \n{}\r\n"])
def test_same_origin_post_performs_one_refresh(live, body):
    server, service = live
    status, headers, response = request(server, "POST", "/api/refresh", body)

    assert status == 200
    assert json.loads(response)["report_id"] == "synthetic-report-2"
    assert service.refresh_calls == 1
    assert headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in headers


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/refresh", 405),
        ("/api/refresh?refresh=1", 404),
        ("/?refresh=1", 404),
        ("/../../configuration.json", 404),
        ("/%2e%2e/secret.html", 404),
        ("/report.html", 404),
        ("/api/latest?path=../../secret", 404),
    ],
)
def test_get_cannot_mutate_or_read_arbitrary_paths(live, path, expected_status):
    server, service = live
    status, _, _ = request(server, path=path)

    assert status == expected_status
    assert service.refresh_calls == 0
    assert service.latest_calls == 0


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "127.0.0.1:1", "127.0.0.1.evil.example:8765"])
def test_external_or_wrong_host_is_rejected(live, host):
    server, service = live
    status, _, _ = request(server, headers={"Host": host})

    assert status == 403
    assert service.refresh_calls == 0
    assert service.latest_calls == 0


@pytest.mark.parametrize("hosts", [[], ["127.0.0.1", "evil.example"]])
def test_missing_and_duplicate_hosts_are_rejected(live, hosts):
    server, service = live
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.putrequest("GET", "/healthz", skip_host=True)
        for host in hosts:
            connection.putheader("Host", host)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()
    assert service.refresh_calls == 0


@pytest.mark.parametrize("origin", ["null", "", "https://evil.example", "http://127.0.0.1:1", "http://localhost:8765"])
def test_cross_origin_post_is_rejected(live, origin):
    server, service = live
    status, _, body = request(server, "POST", "/api/refresh", b"{}", {"Origin": origin})

    assert status == 403
    assert "same-origin" in json.loads(body)["error"]
    assert service.refresh_calls == 0


def test_post_requires_origin_even_when_host_is_local(live):
    server, service = live
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("POST", "/api/refresh", body=b"{}")
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()
    assert service.refresh_calls == 0


def test_localhost_origin_must_match_localhost_host(live):
    server, service = live
    host = f"localhost:{server.server_port}"
    status, _, _ = request(server, "POST", "/api/refresh", b"{}", {"Host": host, "Origin": "http://" + host})
    assert status == 200
    assert service.refresh_calls == 1


def test_cross_site_metadata_is_rejected_even_with_forged_origin(live):
    server, service = live
    status, _, _ = request(server, "POST", "/api/refresh", b"{}", {"Sec-Fetch-Site": "cross-site"})
    assert status == 403
    assert service.refresh_calls == 0


@pytest.mark.parametrize(
    ("body", "headers", "expected_status"),
    [
        (b'{"directory":"../../pilot"}', {}, 400),
        (b"[]", {}, 400),
        (b"{ }", {}, 400),
        (b"{", {}, 400),
        (b"x" * (web.MAX_REQUEST_BODY + 1), {}, 413),
        (b"{}", {"Content-Length": "-1"}, 400),
        (b"{}", {"Content-Length": "invalid"}, 400),
        (b"{}", {"Transfer-Encoding": "chunked"}, 400),
        (b"{}", {"Content-Type": "application/x-www-form-urlencoded"}, 415),
    ],
)
def test_refresh_accepts_no_user_options_or_large_body(live, body, headers, expected_status):
    server, service = live
    status, _, _ = request(server, "POST", "/api/refresh", body, headers)
    assert status == expected_status
    assert service.refresh_calls == 0


def test_options_never_enables_cors(live):
    server, service = live
    status, headers, _ = request(server, "OPTIONS", "/api/refresh", headers={"Origin": "https://evil.example"})
    assert status == 405
    assert "Access-Control-Allow-Origin" not in headers
    assert service.refresh_calls == 0


def test_refresh_exception_preserves_saved_report_and_returns_readable_error(live):
    server, service = live
    old_report = dict(service.report)
    service.failure = RuntimeError('<script>alert("source failure")</script>')
    status, headers, body = request(server, "POST", "/api/refresh", b"{}")

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert "source failure" in json.loads(body)["error"]
    assert service.report == old_report
    assert json.loads(request(server, path="/api/latest")[2]) == old_report
    assert "下方保留上次保存的报告" in request(server)[2]


def test_health_identifies_service_and_resolved_directory_without_refresh(live):
    server, service = live
    status, _, body = request(server, path="/healthz")
    assert status == 200
    assert json.loads(body) == {
        "service": web.SERVICE_ID,
        "data_directory": str(server.data_directory),
        "protocol_path": str(server.protocol_path),
    }
    assert server.server_address[0] == "127.0.0.1"
    assert service.refresh_calls == service.latest_calls == 0
    assert web.existing_server(server.server_port, server.data_directory, server.protocol_path)


def test_existing_server_rejects_different_directory_or_foreign_service(live):
    server, _ = live
    with pytest.raises(RuntimeError, match="occupied"):
        web.existing_server(server.server_port, server.data_directory / "different", server.protocol_path)
    server.identity = lambda: {"service": "another-application"}
    with pytest.raises(RuntimeError, match="occupied"):
        web.existing_server(server.server_port, server.data_directory, server.protocol_path)


def test_absent_server_is_not_reported_as_ready(tmp_path):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    assert not web.existing_server(port, tmp_path, tmp_path / "protocol.json")


def test_reopening_cli_reuses_server_and_opens_browser(live, monkeypatch):
    server, service = live
    opened = []
    monkeypatch.setattr(web.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(web, "create_server", lambda *args, **kwargs: pytest.fail("must reuse the existing server"))
    result = web.main([
        "--data-directory", str(server.data_directory),
        "--protocol", str(server.protocol_path),
        "--port", str(server.server_port), "--open-browser",
    ])
    assert result == 0
    assert opened == [server.url]
    assert service.refresh_calls == 0


def test_cli_port_conflict_is_an_error_not_success(live, capsys):
    server, _ = live
    result = web.main([
        "--data-directory", str(server.data_directory / "other"),
        "--protocol", str(server.protocol_path),
        "--port", str(server.server_port),
    ])
    assert result == 1
    assert "occupied" in capsys.readouterr().err


@pytest.mark.parametrize("matching_directory", [True, False])
def test_second_launcher_bind_race_uses_only_matching_server(live, monkeypatch, matching_directory):
    server, service = live
    actual_probe = web.existing_server
    probes = 0
    opened = []

    def raced_probe(port, data_directory, protocol_path):
        nonlocal probes
        probes += 1
        # The first probe happened just before another launcher bound the port.
        return False if probes == 1 else actual_probe(port, data_directory, protocol_path)

    def lost_bind(*args, **kwargs):
        raise OSError(errno.EADDRINUSE, "another launcher won the port")

    monkeypatch.setattr(web, "existing_server", raced_probe)
    monkeypatch.setattr(web, "create_server", lost_bind)
    monkeypatch.setattr(web.webbrowser, "open", lambda url: opened.append(url) or True)
    directory = server.data_directory if matching_directory else server.data_directory / "different"
    result = web.main([
        "--data-directory", str(directory),
        "--protocol", str(server.protocol_path),
        "--port", str(server.server_port), "--open-browser",
    ])

    assert result == (0 if matching_directory else 1)
    assert opened == ([server.url] if matching_directory else [])
    assert probes == 2
    assert service.refresh_calls == 0
