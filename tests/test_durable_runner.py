from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import io
import pytest

from dx27.adapters.sentinel.atomic_store import exclusive_write
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.file_lock import exclusive_lock
from dx27.adapters.sentinel.store_migration import backup, restore, verify_store
from dx27.adapters.sentinel.supervised_runner import check_worker
from dx27.adapters.calendars.xnys import load_xnys_calendar
from datetime import date, timedelta


def test_lock_releases_after_process_death(tmp_path):
    path = tmp_path / "worker.lock"
    script = "from dx27.adapters.sentinel.file_lock import exclusive_lock; import sys,time;\nwith exclusive_lock(sys.argv[1]):\n print('LOCKED',flush=True);time.sleep(60)"
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(OSError):
            with exclusive_lock(path):
                pass
        child.kill()
        child.wait()
        with exclusive_lock(path):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_atomic_publish_refuses_overwrite_and_partial_staging_not_evidence(tmp_path):
    p = tmp_path / "sealed.json"
    exclusive_write(p, b"original")
    with pytest.raises(FileExistsError):
        exclusive_write(p, b"changed")
    assert p.read_bytes() == b"original"
    store = CaptureStore(tmp_path / "store")
    staging = store.root / "staging" / "incomplete"
    staging.mkdir(parents=True)
    (staging / "payload.bin").write_bytes(b"partial")
    assert store.records() == ()
    row = store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test",
        b"complete",
        datetime(2026, 10, 8, 15, tzinfo=timezone.utc),
    )
    assert store.get(row["capture_id"])[1] == b"complete"


def test_migration_preserves_all_original_bytes_and_times(tmp_path):
    root = tmp_path / "source"
    store = CaptureStore(root)
    row = store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test",
        b"price",
        datetime(2026, 10, 8, 15, tzinfo=timezone.utc),
    )
    (root / "heartbeat.json").write_text("transient")
    archive = tmp_path / "backup.tar.gz"
    manifest = backup(root, archive)
    target = tmp_path / "restored"
    assert restore(archive, target) == manifest
    assert CaptureStore(target).get(row["capture_id"]) == store.get(row["capture_id"])
    assert not (target / "heartbeat.json").exists()
    with pytest.raises(ValueError, match="new target"):
        restore(archive, target)


def test_backup_refuses_active_worker(tmp_path):
    store = CaptureStore(tmp_path / "store")
    lock = store.root / "profiles" / "test" / "worker.lock"
    with exclusive_lock(lock):
        with pytest.raises(OSError):
            backup(store.root, tmp_path / "archive.tar.gz")


def test_restore_rejects_traversal_before_writing(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        entry = tarfile.TarInfo("../escape")
        entry.size = 3
        tar.addfile(entry, io.BytesIO(b"bad"))
    with pytest.raises(ValueError, match="unsafe"):
        restore(archive, tmp_path / "target")
    assert not (tmp_path / "target").exists()


def test_tampered_capture_fails_migration(tmp_path):
    store = CaptureStore(tmp_path / "store")
    row = store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test",
        b"price",
        datetime(2026, 10, 8, 15, tzinfo=timezone.utc),
    )
    (store.root / "captures" / row["capture_id"] / "payload.bin").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="payload changed"):
        backup(store.root, tmp_path / "backup.tar.gz")


def test_monitor_detects_deadline_overdue_and_stale_heartbeat(tmp_path):
    pilot = json.loads(
        Path("research/sentinel/6b-2i-3-clock-coverage/pilot_protocol.json").read_text()
    )
    cal = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    session = cal.get(pilot["decision_sessions"][0])
    now = session.closes_at + timedelta(minutes=30)
    (tmp_path / "heartbeat.json").write_text(
        json.dumps({"last_heartbeat_at": now.isoformat()})
    )
    healthy, reasons, _ = check_worker(tmp_path, pilot, cal, now)
    assert not healthy and reasons == [pilot["decision_sessions"][0] + "-20.json"]
    _, reasons, _ = check_worker(tmp_path, pilot, cal, now + timedelta(minutes=20))
    assert reasons == ["WORKER_HEARTBEAT_STALE_OR_FUTURE"]


def test_verify_missing_store_never_creates_empty_replacement(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="existing capture store"):
        verify_store(missing)
    assert not missing.exists()
