"""Private local refresh and durable visit snapshots for the final Sentinel scope."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from dx27.adapters.sentinel.capture_store import CaptureStore, encoded
from dx27.adapters.sentinel.research_analysis import build_research_trends


PROFILE = {"schema_version": "sentinel-research-live-v1", "purpose": "PRIVATE_DESCRIPTIVE_REPORTS_NOT_PILOT"}


def validate_research_dependencies() -> None:
    missing = []
    for package in ("pypdf", "rapidocr_onnxruntime"):
        try:
            importlib.import_module(package)
        except ImportError:
            missing.append(package)
    if missing:
        raise RuntimeError("研究报告依赖未安装：" + ", ".join(missing) + "; run python -m pip install -e '.[research-report]'")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8"))


@contextmanager
def _writer_lock(path: Path):
    """OS-owned locks are released after a crash, including on Windows."""
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("同一报告目录已有更新正在写入；请稍后刷新") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class LiveReportService:
    def __init__(self, root: Path, protocol_path: Path, *, research_fetchers=None, market_refresh=None, clock=None):
        self.root = Path(root).resolve()
        self.protocol_path = Path(protocol_path).resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._refresh_lock = threading.Lock()
        self._research_fetchers = research_fetchers
        self._market_refresh = market_refresh
        self._initialize()

    def _initialize(self):
        for path in (self.root, *self.root.parents):
            if (path / "configuration.json").exists() or (path / "profiles").is_dir():
                raise ValueError("live reports require a separate directory outside the pilot store")
        marker = self.root / "live-report-profile.json"
        if self.root.exists() and any(self.root.iterdir()) and not marker.exists():
            # Another simultaneous launcher may be atomically publishing its
            # marker. Wait briefly, then still refuse unrelated unmarked stores.
            deadline = time.monotonic() + 1
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            if not marker.exists():
                raise ValueError("use a new live-report directory; existing unmarked stores are refused")
        self.root.mkdir(parents=True, exist_ok=True)
        if marker.exists():
            if json.loads(marker.read_bytes()) != PROFILE:
                raise ValueError("live-report directory profile mismatch")
        else:
            _atomic_json(marker, PROFILE)
        self._child("snapshots").mkdir(exist_ok=True)
        self._child("research-captures").mkdir(exist_ok=True)

    def _child(self, name: str) -> Path:
        path = self.root / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("live-report child directories cannot link to another store")
        return path

    def latest(self) -> dict | None:
        pointer = self.root / "latest.json"
        if not pointer.exists():
            return None
        value = json.loads(pointer.read_bytes())
        if not isinstance(value, dict) or not isinstance(value.get("html"), str):
            raise ValueError("saved report is invalid; original snapshots have been retained")
        return value

    def _observations(self):
        if self._market_refresh is not None:
            return self._market_refresh()
        from dx27.adapters.sentinel.observation_runner import build_report
        from dx27.adapters.sentinel.recorded_runner import capture_sources

        root = self._child("observations")
        if (root / "configuration.json").exists() or (root / "profiles").exists():
            raise ValueError("observation directory is a pilot store; no capture was made")
        if root.exists() and any(root.iterdir()) and not (root / "observation-profile.json").exists():
            raise ValueError("existing unmarked observation directory is refused before capture")
        store = CaptureStore(root)
        marker = root / "observation-profile.json"
        profile = {"schema_version": "sentinel-observation-store-v1", "purpose": "LATEST_VINTAGE_DESCRIPTIVE_ONLY"}
        if not marker.exists():
            with marker.open("xb") as stream:
                stream.write(encoded(profile))
        elif json.loads(marker.read_bytes()) != profile:
            raise ValueError("observation directory profile mismatch")
        capture_sources(store)
        return build_report(store, json.loads(self.protocol_path.read_bytes()), self.clock())

    def _providers(self):
        if self._research_fetchers is not None:
            return self._research_fetchers
        from dx27.adapters.sentinel.factset_research import fetch_factset
        from dx27.adapters.sentinel.yardeni_research import fetch_yardeni
        return {"factset": fetch_factset, "yardeni": fetch_yardeni}

    def _fetch(self, source_id, fetcher, now):
        try:
            capture_root = self._child("research-captures") / source_id
            if capture_root.is_symlink() or not capture_root.resolve().is_relative_to(self.root):
                raise ValueError("research capture directory cannot link to another store")
            value = fetcher(capture_root, now)
            if value.get("source_id") != source_id or value.get("status") not in {"AVAILABLE", "PARTIAL", "SOURCE_ERROR"}:
                raise ValueError("invalid research provider response")
            # Check serialization and finite numbers before saving a snapshot.
            json.dumps(value, allow_nan=False)
            return value
        except Exception as exc:
            return {"source_id": source_id, "status": "SOURCE_ERROR", "retrieved_at": self.clock().isoformat(), "publication_date": None, "source_url": "https://www.factset.com/earningsinsight" if source_id == "factset" else "https://yardeni.com/charts/", "document_id": "", "metrics": [], "captures": [], "errors": [type(exc).__name__ + ": " + str(exc)]}

    def refresh(self) -> dict:
        with self._refresh_lock, _writer_lock(self.root / "refresh.lock"):
            previous = self.latest()
            now = self.clock()
            if now.tzinfo is None:
                raise ValueError("refresh clock requires timezone")
            providers = self._providers()
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {sid: pool.submit(self._fetch, sid, fetcher, now) for sid, fetcher in providers.items()}
                market_future = pool.submit(self._observations)
                sources = [future.result() for future in futures.values()]
                try:
                    report = market_future.result()
                except Exception as exc:
                    report = {
                        "schema_version": "sentinel-observation-v1", "report_kind": "LATEST_VINTAGE_DESCRIPTIVE_ONLY",
                        "session_id": "市场采集不可用", "market_now": {}, "previous_market_now": {},
                        "source_results": [], "freshness_status": "DEGRADED_LATEST_FETCH_FAILED",
                        "latest_fetch_failed_feeds": [], "market_refresh_error": type(exc).__name__ + ": " + str(exc),
                        "admission_status": "BLOCKED_DATA", "production_enabled": False,
                    }
            report["generated_at"] = self.clock().isoformat()
            report["task_id"] = "6B-2K-B"
            report["research_sources"] = sources
            previous_report = previous.get("report") if previous else None
            report["research_trends"] = build_research_trends(sources, previous_report, self.clock())
            report["sentinel_development_status"] = "FROZEN_MAINTENANCE_ONLY"
            from dx27.adapters.sentinel.observation_report import render_html, render_markdown
            html = render_html(report)
            markdown = render_markdown(report)
            identity = hashlib.sha256(encoded(report)).hexdigest()
            result = {"report_id": identity, "generated_at": report["generated_at"], "html": html, "status": report["research_trends"]["status"], "report": report}
            _atomic_json(self.root / "snapshots" / (identity + ".json"), result)
            _atomic_bytes(self.root / "latest.md", markdown.encode("utf-8"))
            # Publish the pointer only after the complete immutable visit is durable.
            _atomic_json(self.root / "latest.json", result)
            return result
