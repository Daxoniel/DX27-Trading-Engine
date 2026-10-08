"""OS-scheduled collector with external liveness alerts; no self-admission."""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore, encoded
from dx27.adapters.sentinel.coverage_pilot import (
    load_configuration,
    read_job,
    validate_pilot,
)
from dx27.adapters.sentinel.file_lock import exclusive_lock
from dx27.adapters.sentinel.source_clocks import ProfileStore, validate_clock_profile
from dx27.adapters.sentinel.store_migration import verify_store


def check_worker(root, pilot, calendar, now):
    heartbeat = root / "heartbeat.json"
    if not heartbeat.exists():
        return False, ["WORKER_HEARTBEAT_NOT_CREATED"], []
    try:
        value = json.loads(heartbeat.read_bytes())
        age = (now - datetime.fromisoformat(value["last_heartbeat_at"])).total_seconds()
    except (ValueError, KeyError):
        return False, ["INVALID_WORKER_HEARTBEAT"], []
    if age < -5 or age > 900:
        return False, ["WORKER_HEARTBEAT_STALE_OR_FUTURE"], []
    overdue = []
    missed = []
    for day in pilot["decision_sessions"]:
        session = calendar.get(day)
        for offset in pilot["capture_offsets_after_close_minutes"]:
            path = root / "jobs" / (day + "-" + str(offset) + ".json")
            if path.exists():
                event = read_job(path)
                if event["status"] == "MISSED":
                    missed.append(path.name)
            elif now > session.closes_at + timedelta(minutes=offset + 8):
                overdue.append(path.name)
        marker = root / "jobs" / (day + "-cutoff.json")
        if now > session.decision_cutoff + timedelta(minutes=8) and not marker.exists():
            overdue.append(marker.name)
    return not overdue, overdue, missed


def ping(url, failed=False):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise ValueError("HTTPS monitoring URL required")
    # URL is secret. Never log it or raw exception text that might contain it.
    endpoint = url.rstrip("/") + ("/fail" if failed else "")
    try:
        with urlopen(
            Request(
                endpoint, headers={"User-Agent": "DX27 Sentinel infrastructure monitor"}
            ),
            timeout=10,
        ) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def update(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--monitor-config", type=Path, required=True)
    parser.add_argument(
        "--pilot",
        type=Path,
        default=Path("research/sentinel/6b-2i-3-clock-coverage/pilot_protocol.json"),
    )
    parser.add_argument(
        "--clocks",
        type=Path,
        default=Path("research/sentinel/6b-2i-3-clock-coverage/clock_profile.json"),
    )
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    pilot, clock = load_configuration(args.pilot, args.clocks)
    config = json.loads(args.monitor_config.read_bytes())
    urls = config["heartbeat_urls"]
    if len(urls) != 1 or any(
        not u.startswith("https://") or "REPLACE" in u for u in urls
    ):
        raise ValueError("one external HTTPS heartbeat required")
    raw = CaptureStore(args.store)
    store = ProfileStore(raw, clock)
    verify_store(raw.root)
    validate_clock_profile(clock, raw)
    calendar = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    validate_pilot(pilot, calendar)
    if args.preflight:
        import platform

        print(
            json.dumps(
                {
                    "platform": platform.system(),
                    "capture_count": len(verify_store(raw.root)),
                    "pilot_first_session": pilot["decision_sessions"][0],
                    "pilot_last_session": pilot["decision_sessions"][-1],
                    "calendar_version": calendar.calendar_version,
                    "deployment_admission": "NOT_READY_TARGET_REBOOT_AND_EMAIL_ACCEPTANCE_PENDING",
                }
            )
        )
        return 0
    with exclusive_lock(raw.root / "supervisor.lock"):
        command = [
            sys.executable,
            "-u",
            "-m",
            "dx27.adapters.sentinel.coverage_pilot",
            "--store",
            str(raw.root),
            "--pilot",
            str(args.pilot),
            "--clocks",
            str(args.clocks),
            "--daemon",
        ]
        log_directory = raw.root / "logs"
        log_directory.mkdir(exist_ok=True)
        log = (log_directory / "collector.log").open("a", encoding="utf-8")
        worker = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        started = time.monotonic()
        last_ping = 0
        ledger_path = store.root / "supervisor-ledger.json"
        notified = (
            set(json.loads(ledger_path.read_bytes()).get("missed_slots", []))
            if ledger_path.exists()
            else set()
        )
        try:
            while True:
                now = datetime.now(timezone.utc)
                code = worker.poll()
                if code is not None:
                    normal = (
                        code == 0
                        and now
                        >= calendar.get(pilot["decision_sessions"][-1]).decision_cutoff
                    )
                    if not normal:
                        for url in urls:
                            ping(url, True)
                    return 0 if normal else 1
                healthy, reasons, missed = check_worker(
                    store.root, pilot, calendar, now
                )
                if time.monotonic() - started < 60:
                    healthy = True  # startup only, never a coverage verdict
                fresh = set(missed) - notified
                if time.monotonic() - last_ping >= 60 or fresh:
                    failed = not healthy or bool(fresh)
                    delivered = [ping(url, failed) for url in urls]
                    if fresh and all(delivered):
                        notified.update(fresh)
                        update(ledger_path, {"missed_slots": sorted(notified)})
                    last_ping = time.monotonic()
                    update(
                        store.root / "supervisor-health.json",
                        {
                            "observed_at": now.isoformat(),
                            "supervisor_pid": os.getpid(),
                            "worker_pid": worker.pid,
                            "worker_healthy": healthy,
                            "reasons": reasons,
                            "monitor_delivery": delivered,
                            "missed_slot_notifications": sorted(notified),
                            "deployment_admission": "NOT_READY_UNTIL_TARGET_REBOOT_AND_EMAIL_ACCEPTANCE",
                            "mode": "OS_SCHEDULED_CANDIDATE_NOT_SELF_CERTIFIED",
                        },
                    )
                if not healthy and time.monotonic() - started > 60:
                    worker.terminate()
                    worker.wait(timeout=30)
                    return 1
                time.sleep(20)
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
