"""Supervise sealed historical simulation; no network or real-order capability."""

import argparse
from bisect import bisect_right
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
from tempfile import NamedTemporaryFile
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from dx27.adapters.intraday.cli import read_config, write_report
from dx27.adapters.intraday.closed_loop import closed_loop_manifest, run_closed_loop
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.recorded_shadow import GENESIS, ShadowJournal, _hash, _json
from dx27.application.intraday_replay import replay_sessions
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.replay_config import IntradayReplayConfig


class RunnerError(RuntimeError):
    """Stable non-sensitive operational error; never persist exception text."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path, value):
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=path.name + ".tmp-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _busy(path):
    """Probe an existing OS-released SQLite lease without creating/modifying it.

    Avoid PID signaling, which is unsafe as a liveness probe on Windows.
    """
    if not path.exists():
        return False
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
        return False
    except sqlite3.OperationalError as exc:
        if exc.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return True
        raise
    finally:
        connection.close()


def _journal_snapshot(path, manifest):
    if not path.exists():
        return dict(frames=0, journal_chain_sha256=GENESIS, complete=False)
    if _busy(Path(str(path) + ".lease.sqlite3")):
        raise RunnerError("JOURNAL_BUSY")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)
    try:
        connection.execute("BEGIN")
        stored = connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        if stored is None or stored[0] != _json(manifest):
            raise RunnerError("MANIFEST_MISMATCH")
        count, chain, complete = 0, GENESIS, False
        for seq, key, payload, seal in connection.execute("SELECT sequence, frame_key, payload, chain FROM frames ORDER BY sequence"):
            count += 1
            if complete or seq != count or seal != _hash(chain + "\n" + key + "\n" + payload):
                raise RunnerError("JOURNAL_INTEGRITY_FAILURE")
            frame = json.loads(payload)
            if key != frame["kind"] + ":" + frame["as_of"]:
                raise RunnerError("JOURNAL_INTEGRITY_FAILURE")
            complete = frame["kind"] == "RUN_COMPLETED"
            chain = seal
        return dict(frames=count, journal_chain_sha256=chain, complete=complete)
    except sqlite3.OperationalError as exc:
        if exc.sqlite_errorcode == sqlite3.SQLITE_READONLY_ROLLBACK:
            return dict(frames=None, journal_chain_sha256=None, complete=False,
                        storage_recovery_required=True)
        raise RunnerError("JOURNAL_INVALID_OR_UNAVAILABLE") from None
    except (sqlite3.DatabaseError, ValueError, KeyError, TypeError):
        raise RunnerError("JOURNAL_INVALID_OR_UNAVAILABLE") from None
    finally:
        connection.close()


def preflight(dataset, journal, run_directory, config=None, profile=None, *, output=None, protected_paths=()):
    """Read-only validation; neither reports nor lease databases are created."""
    config, profile = config or IntradayReplayConfig(), profile or HistoricalExecutionProfile()
    journal, directory = Path(journal).resolve(), Path(run_directory).resolve()
    protected = {Path(p).resolve() for p in protected_paths}
    controls = {(directory / name).resolve() for name in ("health.json", "owner.sqlite3", "stop.json")}
    writes = controls | {journal, Path(str(journal) + ".lease.sqlite3")}
    if len(writes) != 5 or writes & protected or journal == directory or journal.is_dir() or any(p.parent != directory for p in controls):
        raise RunnerError("PATH_CONFLICT")
    if directory.exists() and not directory.is_dir():
        raise RunnerError("PATH_CONFLICT")
    if output is not None:
        output = Path(output).resolve()
        if output.exists() or any(output == p or output in p.parents for p in writes | protected) or directory in output.parents:
            raise RunnerError("REPORT_PATH_CONFLICT")
    try:
        if config.opening_volume and dataset.provenance.get("feed") != "sip" and dataset.provenance.get("source") != "SYNTHETIC_DEMO":
            raise RunnerError("OPENING_VOLUME_SOURCE_UNSUPPORTED")
        manifest = closed_loop_manifest(dataset, config, profile)
        _, sessions = replay_sessions(dataset)
        opens = [s.opens_at for s in sessions]
        symbols = set(b.symbol for b in dataset.bars) | set(dataset.provenance.get("symbols", ()))
        regular, zero = 0, 0
        for bar in dataset.bars:
            index = bisect_right(opens, bar.timestamp) - 1
            if index >= 0 and bar.timestamp < sessions[index].closes_at:
                regular += 1
                zero += bar.volume == 0
        expected = sum(int((s.closes_at - s.opens_at).total_seconds() / 60) for s in sessions) * len(symbols)
        active = sum(config.decision_start is None or s.opens_at.astimezone(ZoneInfo("America/New_York")).date() >= config.decision_start for s in sessions)
        if not regular or not active:
            raise RunnerError("NO_ACTIVE_REGULAR_SESSION_DATA")
        snapshot = _journal_snapshot(journal, manifest)
        identity = _hash(_json(manifest))
        if (directory / "health.json").exists():
            previous = _read_json(directory / "health.json")
            if previous.get("manifest_sha256") != identity or previous.get("journal") != str(journal):
                raise RunnerError("RUN_DIRECTORY_MISMATCH")
        if _busy(directory / "owner.sqlite3"):
            raise RunnerError("RUNNER_BUSY")
    except RunnerError:
        raise
    except (ValueError, TypeError, KeyError, OSError, sqlite3.DatabaseError):
        raise RunnerError("PREFLIGHT_INVALID_OR_UNAVAILABLE") from None
    return dict(task="P2-H3", status="STORAGE_RECOVERY_REQUIRED" if snapshot.get("storage_recovery_required") else "READY", manifest_sha256=identity,
                journal=str(journal), recovery="DETERMINISTIC_OFFLINE_REBUILD",
                journal_snapshot=snapshot, input_bars=len(dataset.bars), sessions=len(sessions),
                active_sessions=active, regular_session_bars=regular, missing_regular_bars=expected - regular,
                zero_volume_bars=zero, data_quality_complete=regular == expected and zero == 0,
                real_broker_orders_enabled=False, realtime_data_verified=False,
                algorithm_optimization_performed=False)


@contextmanager
def _owner(directory):
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "owner.sqlite3", timeout=0)
    try:
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            raise RunnerError("RUNNER_BUSY") from None
        yield
    finally:
        connection.close()


def health(run_directory, *, stale_after_seconds=30):
    if isinstance(stale_after_seconds, bool) or not math.isfinite(stale_after_seconds) or stale_after_seconds <= 0:
        raise RunnerError("INVALID_STALENESS_LIMIT")
    directory = Path(run_directory)
    if not (directory / "health.json").exists():
        return dict(status="NOT_STARTED", owner_active=False, real_broker_orders_enabled=False)
    try:
        value = _read_json(directory / "health.json")
        owner = _busy(directory / "owner.sqlite3")
        age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(value["updated_at"])).total_seconds())
        recorded = value["status"]
        if recorded in {"STARTING", "REBUILDING", "RUNNING", "RECOVERING"}:
            value["status"] = "INTERRUPTED" if not owner else "STALLED" if age > stale_after_seconds else recorded
        value.update(recorded_status=recorded, owner_active=owner, heartbeat_age_seconds=age)
        return value
    except (OSError, ValueError, TypeError, KeyError, sqlite3.DatabaseError):
        raise RunnerError("HEALTH_UNAVAILABLE") from None


def request_stop(run_directory):
    directory = Path(run_directory)
    value = health(directory)
    if not value["owner_active"] or value["recorded_status"] not in {"STARTING", "REBUILDING", "RUNNING", "RECOVERING"}:
        raise RunnerError("RUNNER_NOT_RUNNING")
    request = dict(attempt_id=value["attempt_id"], requested_at=_now())
    _atomic_json(directory / "stop.json", request)
    return dict(status="STOP_REQUESTED", attempt_id=value["attempt_id"], real_broker_orders_enabled=False)


def _retryable(exc):
    # Never retry validation, accounting, corruption, disk-full or uncertain orders.
    return isinstance(exc, OSError) and exc.errno in {errno.EINTR, errno.EIO, errno.ETIMEDOUT}


def run_managed(dataset, journal, run_directory, config=None, profile=None, *, output=None,
                protected_paths=(), stop_after_minutes=None, max_restarts=0, control=None):
    if isinstance(max_restarts, bool) or not isinstance(max_restarts, int) or not 0 <= max_restarts <= 3:
        raise RunnerError("INVALID_RESTART_LIMIT")
    if stop_after_minutes is not None and (isinstance(stop_after_minutes, bool) or not isinstance(stop_after_minutes, int) or stop_after_minutes < 1):
        raise RunnerError("INVALID_PAUSE_LIMIT")
    config, profile = config or IntradayReplayConfig(), profile or HistoricalExecutionProfile()
    check = preflight(dataset, journal, run_directory, config, profile, output=output, protected_paths=protected_paths)
    directory = Path(run_directory).resolve()
    with _owner(directory):
        # Recheck identity after ownership: concurrent starters cannot overwrite status.
        if (directory / "health.json").exists():
            previous = _read_json(directory / "health.json")
            if previous.get("manifest_sha256") != check["manifest_sha256"] or previous.get("journal") != check["journal"]:
                raise RunnerError("RUN_DIRECTORY_MISMATCH")
        state = dict(task="P2-H3", status="STARTING", attempt_id=uuid4().hex, pid=os.getpid(),
                     manifest_sha256=check["manifest_sha256"], journal=check["journal"],
                     started_at=_now(), updated_at=_now(), restarts=0, progress=None, account=None, receipt=None,
                     error_code=None, storage_recovery_performed=False, report_status="NOT_REQUESTED" if output is None else "PENDING",
                     real_broker_orders_enabled=False, realtime_data_verified=False,
                     algorithm_optimization_performed=False, recovery="DETERMINISTIC_OFFLINE_REBUILD")
        last_write = 0.0

        def persist():
            nonlocal last_write
            state["updated_at"] = _now()
            _atomic_json(directory / "health.json", state)
            last_write = time.monotonic()

        def observe(progress):
            state["progress"] = progress
            if progress["account"] is not None:
                state["account"] = progress["account"]
            phase = "REBUILDING" if progress["frames"] <= progress["existing_frames"] else "RUNNING"
            changed = phase != state["status"]
            state["status"] = phase
            # Heartbeats during prefix verification and new commits. Monitor state
            # is operational metadata and does not enter the deterministic journal.
            if changed or time.monotonic() - last_write >= 2:
                persist()
            stop = directory / "stop.json"
            requested = stop.exists() and _read_json(stop).get("attempt_id") == state["attempt_id"]
            return bool(requested or (control is not None and control(dict(progress))))

        try:
            persist()
            if check["journal_snapshot"].get("storage_recovery_required"):
                state["status"] = "RECOVERING"
                persist()
                # Writable SQLite rollback is authorized only in run, under
                # both ownership leases. No frames are appended here.
                with ShadowJournal(journal, closed_loop_manifest(dataset, config, profile)):
                    pass
                state["storage_recovery_performed"] = True
                persist()
            for attempt in range(max_restarts + 1):
                try:
                    receipt, result = run_closed_loop(dataset, journal, config, profile,
                        stop_after_minutes=stop_after_minutes, control=observe)
                    break
                except Exception as exc:
                    if attempt >= max_restarts or not _retryable(exc):
                        raise
                    state.update(status="RECOVERING", restarts=attempt + 1, error_code="TRANSIENT_STORAGE_FAILURE")
                    persist()
                    # The next call always rebuilds into a fresh simulator and
                    # verifies the committed prefix; no live broker resubmission.
            state.update(status={"COMPLETE_CLOSED_LOOP": "COMPLETED", "INCOMPLETE_CLOSED_LOOP": "INCOMPLETE"}.get(receipt["status"], receipt["status"]),
                         receipt=receipt, error_code=None)
            if state["progress"] is not None:
                state["progress"].update({key: receipt[key] for key in
                    ("frames", "verified_prefix_frames", "appended_frames", "journal_chain_sha256")})
                state["progress"]["committed_frames"] = max(state["progress"]["committed_frames"], receipt["frames"])
                if result is not None:
                    state["progress"]["kind"] = "RUN_COMPLETED"
            if output is not None and result is not None:
                try:
                    write_report(result, output)
                    _atomic_json(Path(output) / "runner-receipt.json", receipt)
                    state["report_status"] = "WRITTEN"
                except Exception:
                    state["report_status"] = "FAILED"
                    raise RunnerError("REPORT_WRITE_FAILED") from None
            elif output is not None:
                state["report_status"] = "DEFERRED"
            persist()
            return dict(state), result
        except BaseException as exc:
            code = str(exc) if isinstance(exc, RunnerError) else "RUN_INTERRUPTED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "RUN_FAILED"
            state.update(status="INTERRUPTED" if code == "RUN_INTERRUPTED" else "FAILED", error_code=code)
            try:
                persist()
            except (OSError, ValueError):
                pass  # Status inspection sees released ownership after a crash.
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "run"):
        p = commands.add_parser(command)
        p.add_argument("--input", required=True)
        p.add_argument("--journal", required=True)
        p.add_argument("--run-directory", required=True)
        p.add_argument("--config")
        p.add_argument("--decision-start")
        p.add_argument("--profile")
        p.add_argument("--output")
        if command == "run":
            p.add_argument("--stop-after-minutes", type=int)
            p.add_argument("--max-restarts", type=int, default=0)
    for command in ("status", "stop"):
        p = commands.add_parser(command)
        p.add_argument("--run-directory", required=True)
        if command == "status":
            p.add_argument("--stale-after-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = health(args.run_directory, stale_after_seconds=args.stale_after_seconds)
            print(_json(result))
            return 0 if result["status"] in {"COMPLETED", "RUNNING", "REBUILDING", "RECOVERING", "STARTING", "PAUSED", "STOPPED"} else 4
        if args.command == "stop":
            print(_json(request_stop(args.run_directory)))
            return 0
        dataset, config = load_csv(args.input), read_config(args.config, args.decision_start)
        values = _read_json(Path(args.profile)) if args.profile else {}
        profile = HistoricalExecutionProfile(**values)
        protected = [args.input, str(args.input) + ".metadata.json", str(args.input) + ".raw.jsonl"]
        protected.extend(p for p in (args.config, args.profile) if p)
        options = dict(output=args.output, protected_paths=protected)
        if args.command == "preflight":
            check = preflight(dataset, args.journal, args.run_directory, config, profile, **options)
            print(_json(check))
            return 0 if check["status"] == "READY" else 4
        stopping = False

        def signal_stop(*_):
            nonlocal stopping
            stopping = True

        original = {sig: signal.signal(sig, signal_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            state, _ = run_managed(dataset, args.journal, args.run_directory, config, profile,
                                  stop_after_minutes=args.stop_after_minutes, max_restarts=args.max_restarts,
                                  control=lambda _: stopping, **options)
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)
        print(_json(state))
        return 0 if state["status"] == "COMPLETED" else 3 if state["status"] in {"PAUSED", "STOPPED"} else 2
    except Exception as exc:
        code = str(exc) if isinstance(exc, RunnerError) else "INPUT_OR_RUNTIME_FAILURE"
        print(_json(dict(task="P2-H3", status="FAILED", error_code=code, real_broker_orders_enabled=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
