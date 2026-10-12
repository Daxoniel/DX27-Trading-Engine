"""Loopback-only browser entry point for an isolated Sentinel research report.

Opening the page shows the last saved report and makes one explicit refresh
request. GET requests never collect data. This module does not serve files or
open the Windows pilot store.
"""

from __future__ import annotations

import argparse
import errno
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from typing import Callable, Protocol
import webbrowser


SERVICE_ID = "dx27-sentinel-research-live-v1"
MAX_REQUEST_BODY = 1024
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_PROTOCOL = _REPOSITORY_ROOT / "research/sentinel/6b-2g-contracts/protocol.json"
_DEFAULT_DIRECTORY = _REPOSITORY_ROOT / "work/sentinel-research-live"


class ReportService(Protocol):
    def refresh(self) -> dict: ...

    def latest(self) -> dict | None: ...


_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel · 最新研究观察</title>
<style>
body{margin:0;font:16px/1.6 system-ui,sans-serif;background:#f4f5f7;color:#17212b}
header{padding:18px 24px;background:white;border-bottom:1px solid #d8dde3}
h1{font-size:22px;margin:0 0 8px}p{margin:4px 0}
#status{font-weight:600}#error{color:#a42323;white-space:pre-wrap}
#saved{color:#596572}iframe{display:block;width:100%;height:calc(100vh - 175px);min-height:600px;border:0}iframe[hidden]{display:none}
</style></head><body>
<header><h1>Sentinel · 最新研究观察</h1>
<p id="status" role="status" aria-live="polite">正在更新：采集当前公开数据、检查来源并生成报告……</p>
<p id="saved"></p><p id="error" role="alert"></p>
<p>每次打开或重新加载都会检查一次。公开研究按各自频率发布，没有新资料时指标可能保持相同。</p>
</header>
<iframe id="report" title="市场研究观察报告" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" hidden></iframe>
<script>
"use strict";
const statusNode = document.getElementById("status");
const savedNode = document.getElementById("saved");
const errorNode = document.getElementById("error");
const frame = document.getElementById("report");
let savedReport = null;
function showReport(report, old) {
  if (!report || typeof report.html !== "string") return false;
  savedReport = report;
  frame.srcdoc = '<base target="_blank">' + report.html;
  frame.hidden = false;
  let stamp = "时间未提供";
  if (typeof report.generated_at === "string") {
    const date = new Date(report.generated_at);
    if (!Number.isNaN(date.getTime())) stamp = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Europe/Berlin", dateStyle: "medium", timeStyle: "long"
    }).format(date) + "（柏林）";
  }
  savedNode.textContent = (old ? "当前显示上次保存的报告（不是本次更新结果）：" : "本次报告生成时间：") + stamp;
  return true;
}
async function loadSaved() {
  try {
    const response = await fetch("/api/latest", {cache: "no-store"});
    if (response.ok) showReport(await response.json(), true);
  } catch (_) { /* A failed cache lookup must not prevent the refresh. */ }
}
async function refresh() {
  try {
    const response = await fetch("/api/refresh", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: "{}", cache: "no-store"
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : "报告更新失败");
    if (!showReport(result, false)) throw new Error("更新返回的报告无效");
    statusNode.textContent = "本次更新已完成。请查看报告中的来源状态与数据时间。";
  } catch (error) {
    errorNode.textContent = error instanceof Error ? error.message : String(error);
    statusNode.textContent = savedReport ? "本次更新失败。下方保留上次保存的报告。" : "本次更新失败，尚无已保存的报告。";
    if (savedReport) showReport(savedReport, true);
  }
}
loadSaved().finally(refresh);
</script></body></html>"""


class ObservationHTTPServer(ThreadingHTTPServer):
    """A service bound exclusively to the IPv4 loopback interface."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        port: int,
        service: ReportService,
        data_directory: Path,
        protocol_path: Path,
    ):
        self.service = service
        self.data_directory = data_directory.resolve()
        self.protocol_path = protocol_path.resolve()
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"

    def identity(self) -> dict:
        return {
            "service": SERVICE_ID,
            "data_directory": str(self.data_directory),
            "protocol_path": str(self.protocol_path),
        }


class _Handler(BaseHTTPRequestHandler):
    server: ObservationHTTPServer
    server_version = "SentinelResearch/1"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args: object) -> None:
        # Request targets can contain arbitrary text; do not echo them to logs.
        pass

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        if content_type.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "connect-src 'self'; frame-src 'self' about:; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'",
            )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: object) -> None:
        self._respond(
            status,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _host(self) -> str | None:
        values = self.headers.get_all("Host", [])
        if len(values) != 1:
            return None
        host = values[0].lower()
        allowed = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        if self.server.server_port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        return host if host in allowed else None

    def _valid_host(self) -> bool:
        if self._host() is None:
            self._json(403, {"error": "Only the local report host is allowed."})
            return False
        return True

    def do_GET(self) -> None:
        if not self._valid_host():
            return
        if self.path == "/":
            self._respond(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/healthz":
            self._json(200, self.server.identity())
        elif self.path == "/api/latest":
            try:
                report = self.server.service.latest()
                if report is None:
                    self._json(404, {"error": "No saved research report yet.", "report": None})
                else:
                    self._json(200, report)
            except Exception as error:
                self._json(500, {"error": f"Saved report unavailable: {error}"})
        elif self.path == "/api/refresh":
            self._json(405, {"error": "Use a same-origin POST to refresh the report."})
        else:
            self._json(404, {"error": "Unknown report endpoint."})

    def do_POST(self) -> None:
        if not self._valid_host():
            return
        if self.path != "/api/refresh":
            self._json(404, {"error": "Unknown report endpoint."})
            return
        origins = self.headers.get_all("Origin", [])
        if origins != ["http://" + str(self._host())]:
            self._json(403, {"error": "A same-origin browser request is required."})
            return
        if self.headers.get("Sec-Fetch-Site") in {"cross-site", "none"}:
            self._json(403, {"error": "Cross-site refresh requests are refused."})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Transfer-Encoding") or len(lengths) > 1:
            self._json(400, {"error": "Unsupported request body framing."})
            return
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            self._json(400, {"error": "Invalid request body length."})
            return
        if length < 0:
            self._json(400, {"error": "Invalid request body length."})
            return
        if length > MAX_REQUEST_BODY:
            self._json(413, {"error": "Refresh request body is too large."})
            return
        content_type = self.headers.get("Content-Type", "application/json").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._json(415, {"error": "Refresh accepts only an empty JSON request."})
            return
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError):
            self._json(400, {"error": "Could not read the refresh request body."})
            return
        if len(body) != length or body.strip() not in (b"", b"{}"):
            self._json(400, {"error": "Refresh accepts only an empty body or {}."})
            return
        try:
            self._json(200, self.server.service.refresh())
        except Exception as error:
            self._json(500, {"error": f"Report refresh failed: {error}"})

    def do_OPTIONS(self) -> None:
        if self._valid_host():
            self._json(405, {"error": "Cross-origin access is not enabled."})


def _default_service_factory(root: Path, protocol_path: Path) -> ReportService:
    from dx27.adapters.sentinel.research_service import (
        LiveReportService,
        validate_research_dependencies,
    )

    validate_research_dependencies()
    return LiveReportService(root=root, protocol_path=protocol_path)


def create_server(
    data_directory: Path,
    protocol_path: Path,
    port: int = 8765,
    *,
    service_factory: Callable[[Path, Path], ReportService] | None = None,
) -> ObservationHTTPServer:
    """Construct an isolated service; a port of zero is useful in local tests."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    service = (service_factory or _default_service_factory)(data_directory, protocol_path)
    return ObservationHTTPServer(port, service, data_directory, protocol_path)


def existing_server(port: int, data_directory: Path, protocol_path: Path) -> bool:
    """Recognize our matching service or reject an occupied/unknown port."""
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        body = response.read(8193)
        identity = json.loads(body) if len(body) <= 8192 else None
        expected = {
            "service": SERVICE_ID,
            "data_directory": str(data_directory.resolve()),
            "protocol_path": str(protocol_path.resolve()),
        }
        if response.status != 200 or identity != expected:
            raise RuntimeError(
                f"Port {port} is occupied by another service or a different research directory. "
                "Use its matching settings or choose another --port."
            )
        return True
    except ConnectionRefusedError:
        return False
    except OSError as error:
        if error.errno == errno.ECONNREFUSED:
            return False
        raise RuntimeError(f"Cannot verify the service on port {port}: {error}") from error
    except (ValueError, EOFError, HTTPException) as error:
        raise RuntimeError(f"Port {port} does not host the Sentinel research service.") from error
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", type=Path, default=_DEFAULT_DIRECTORY)
    parser.add_argument("--protocol", type=Path, default=_DEFAULT_PROTOCOL)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    url = f"http://127.0.0.1:{args.port}/"
    try:
        if existing_server(args.port, args.data_directory, args.protocol):
            print(f"Reusing Sentinel research report: {url}", flush=True)
            if args.open_browser and not webbrowser.open(url):
                print(f"Open this URL in your browser: {url}", file=sys.stderr, flush=True)
            return 0
        try:
            server = create_server(args.data_directory, args.protocol, args.port)
        except OSError as error:
            # A simultaneous second launcher may win the bind race.
            if error.errno in {errno.EADDRINUSE, 10048} and existing_server(
                args.port, args.data_directory, args.protocol
            ):
                if args.open_browser:
                    webbrowser.open(url)
                return 0
            raise
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"Cannot start the research report: {error}", file=sys.stderr)
        return 1
    print(f"Sentinel research report is ready: {url}", flush=True)
    if args.open_browser and not webbrowser.open(url):
        print(f"Open this URL in your browser: {url}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
