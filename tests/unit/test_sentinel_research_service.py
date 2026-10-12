from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from dx27.adapters.sentinel.research_service import LiveReportService, _writer_lock

NOW = datetime(2026, 2, 10, 12, tzinfo=timezone.utc)


def market():
    return dict(session_id="2026-02-09", market_now={}, previous_market_now={}, source_results=[], freshness_status="LATEST_ATTEMPTS_SUCCEEDED")


def provider(sid, value=2):
    def fetch(root, now):
        root.mkdir(parents=True, exist_ok=True)
        return dict(source_id=sid, status="AVAILABLE", retrieved_at=now.isoformat(), publication_date="2026-02-09", source_url="https://example.com", document_id="synthetic", errors=[], captures=[], metrics=[dict(metric_id="earnings_revision_pct", subject_id="information_technology", unit="percent", value=value, target_period="Q1 2026", baseline_date="2025-12-31", observation_date="2026-02-09", reference_id="REF-SYNTHETIC", locator="synthetic page 2")])
    return fetch


def service(path, **kwargs):
    return LiveReportService(path, path.parent / "unused-synthetic-protocol.json", research_fetchers={"factset": provider("factset"), "yardeni": provider("yardeni")}, market_refresh=market, clock=lambda: NOW, **kwargs)


def test_restart_preserves_snapshots_and_uses_actual_previous_report(tmp_path):
    root = tmp_path / "reports"
    first = service(root).refresh()
    resumed = service(root)
    assert resumed.latest()["report_id"] == first["report_id"]
    second = resumed.refresh()
    assert second["report"]["research_trends"]["change_status"] == "UNCHANGED"
    assert second["report"]["research_trends"]["compared_to"] == first["generated_at"]
    assert list((root / "snapshots").glob("*.json"))


def test_failed_provider_is_saved_as_new_failure_not_previous_values(tmp_path):
    root = tmp_path / "reports"
    service(root).refresh()
    runner = service(root)
    def failed(root, now):
        raise OSError("synthetic latest fetch failure")
    runner._research_fetchers = {"factset": failed, "yardeni": failed}
    result = runner.refresh()
    assert result["status"] == "UNAVAILABLE"
    assert all(s["metrics"] == [] for s in result["report"]["research_sources"])
    assert runner.latest()["report_id"] == result["report_id"]
    assert "synthetic latest fetch failure" in result["html"]


def test_market_failure_does_not_hide_current_research(tmp_path):
    runner = service(tmp_path / "reports")
    def failed():
        raise OSError("synthetic price fetch failure")
    runner._market_refresh = failed
    result = runner.refresh()
    assert result["status"] == "AVAILABLE"
    assert result["report"]["freshness_status"] == "DEGRADED_LATEST_FETCH_FAILED"
    assert result["report"]["market_refresh_error"]


@pytest.mark.parametrize("location", ["direct", "descendant"])
def test_pilot_directory_cannot_be_used_even_through_descendant(tmp_path, location):
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "configuration.json").write_text("{}")
    target = pilot if location == "direct" else pilot / "reports"
    with pytest.raises(ValueError, match="pilot"):
        service(target)
    assert not (target / "live-report-profile.json").exists()


def test_existing_unmarked_or_wrong_profile_directory_is_refused(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    (root / "unrelated.json").write_text("{}")
    with pytest.raises(ValueError, match="unmarked"):
        service(root)
    (root / "live-report-profile.json").write_text("{}")
    with pytest.raises(ValueError, match="profile mismatch"):
        service(root)


def test_same_store_excludes_another_process_writer(tmp_path):
    runner = service(tmp_path / "reports")
    with _writer_lock(runner.root / "refresh.lock"):
        with pytest.raises(RuntimeError, match="更新正在写入"):
            runner.refresh()
    assert runner.latest() is None
    assert runner.refresh()["report_id"]


def test_corrupt_latest_is_reported_without_clearing_archive(tmp_path):
    runner = service(tmp_path / "reports")
    original = runner.refresh()
    snapshot = runner.root / "snapshots" / (original["report_id"] + ".json")
    (runner.root / "latest.json").write_text('{"invalid":true}')
    with pytest.raises(ValueError, match="invalid"):
        runner.refresh()
    assert json.loads(snapshot.read_text())["report_id"] == original["report_id"]


def test_child_pilot_is_rejected_before_capture(tmp_path, monkeypatch):
    runner = service(tmp_path / "reports")
    runner._market_refresh = None
    child = runner.root / "observations"
    child.mkdir()
    (child / "configuration.json").write_text("{}")
    called = []
    monkeypatch.setattr("dx27.adapters.sentinel.recorded_runner.capture_sources", lambda store: called.append(store))
    with pytest.raises(ValueError, match="pilot"):
        runner._observations()
    assert not called
    assert not (child / "observation-profile.json").exists()


def test_symlinked_capture_store_is_not_used(tmp_path):
    runner = service(tmp_path / "reports")
    runner._market_refresh = None
    target = tmp_path / "unrelated"
    target.mkdir()
    try:
        (runner.root / "observations").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this execution account cannot create filesystem symlinks")
    with pytest.raises(ValueError, match="another store"):
        runner._observations()
    assert not list(target.iterdir())


def test_markdown_failure_does_not_publish_new_latest(tmp_path, monkeypatch):
    import dx27.adapters.sentinel.research_service as module
    runner = service(tmp_path / "reports")
    first = runner.refresh()
    runner._research_fetchers["factset"] = provider("factset", value=-4)
    original = module._atomic_bytes
    def fail_markdown(path, payload):
        if path.name == "latest.md":
            raise OSError("synthetic markdown write failure")
        original(path, payload)
    monkeypatch.setattr(module, "_atomic_bytes", fail_markdown)
    with pytest.raises(OSError, match="markdown"):
        runner.refresh()
    assert runner.latest()["report_id"] == first["report_id"]


def test_simultaneous_initial_launchers_obtain_same_complete_profile(tmp_path):
    root = tmp_path / "reports"
    with ThreadPoolExecutor(max_workers=4) as pool:
        runners = list(pool.map(lambda _: service(root), range(4)))
    assert len(runners) == 4
    assert all(r.root == root for r in runners)
