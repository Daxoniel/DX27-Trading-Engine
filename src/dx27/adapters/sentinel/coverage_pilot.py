"""Frozen consecutive-cutoff pilot, auditable polling slots and causal coverage."""

import argparse
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore, encoded
from dx27.adapters.sentinel.recorded_runner import capture_sources
from dx27.adapters.sentinel.recorded_sources import binding_for, normalize_capture, CORE
from dx27.adapters.sentinel.source_clocks import ProfileStore, validate_clock_profile
from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.market_state import MarketStateBuilder, SensorRegistry
from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.research.composite_reference import (
    ReferenceBuilder,
    GROUPS,
    PAIRS,
)


def load_configuration(protocol_path, clock_path):
    protocol = json.loads(protocol_path.read_bytes())
    clock = json.loads(clock_path.read_bytes())
    lock = json.loads((protocol_path.parent / "pilot_lock.json").read_bytes())["files"]
    for path in (protocol_path, clock_path):
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock[path.name]:
            raise ValueError("pilot lock changed")
    if (
        protocol["clock_profile_sha256"]
        != hashlib.sha256(clock_path.read_bytes()).hexdigest()
    ):
        raise ValueError("clock profile changed")
    return protocol, clock


def validate_pilot(pilot, calendar):
    if pilot["calendar_version"] != calendar.calendar_version:
        raise ValueError("pilot calendar changed")
    days = pilot["decision_sessions"]
    first = calendar.get(days[0])
    position = calendar.sessions.index(first)
    if days != [s.session_id for s in calendar.sessions[position : position + 20]]:
        raise ValueError("20 consecutive sessions required")
    if datetime.fromisoformat(pilot["activated_at"]) >= first.opens_at:
        raise ValueError("pilot must freeze before first session opens")
    if (
        pilot["minimum_completed_sessions"] != 20
        or pilot["operational_coverage_min"] != 0.95
    ):
        raise ValueError("pilot acceptance changed")
    if (
        pilot["capture_offsets_after_close_minutes"] != [20, 60, 100, 115]
        or pilot["slot_grace_minutes"] != 4
    ):
        raise ValueError("poll schedule changed")
    if tuple(pilot["required_feed_ids"]) != CORE:
        raise ValueError("required feed denominator changed")
    if pilot["source_age_zero_S_feed_ids"] != ["spy", "rsp", "vix", "hy_oas"]:
        raise ValueError("S source denominator changed")


def load_inputs(store, protocol, calendar, as_of, min_day, clock):
    validate_clock_profile(clock, store)
    for path in (store.root / "bindings").glob("*.json"):
        store.binding_record(path.stem)
    records = sorted(
        (
            r
            for r in store.records()
            if datetime.fromisoformat(r["first_seen_at"]) <= as_of
        ),
        key=lambda r: r["first_seen_at"],
    )
    bindings = {}
    points = []
    parsing = []
    for record in records:
        feed = record["feed_id"]
        if feed.endswith("_metadata"):
            continue
        result = {"capture_id": record["capture_id"], "feed_id": feed}
        try:
            raw = store.get(record["capture_id"])[1]
            binding, qualifiers = binding_for(
                feed, record, raw, store, calendar, as_of, clock, records
            )
            normalized, counts = normalize_capture(
                feed, binding, record, raw, calendar, clock, min_day
            )
            bindings[feed] = binding
            points.extend(normalized)
            result.update(status="PARSED", **counts)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            result.update(status="SOURCE_ERROR", reason=str(exc))
        parsing.append(result)
    builder = MarketStateBuilder(
        SensorRegistry.from_protocol(protocol), calendar, tuple(bindings.values())
    )
    return builder, tuple(points), records, parsing


def latest_at_cutoff(points, cutoff):
    """Compact revisions separately for each original cutoff, preserving ties."""
    groups = {}
    for p in points:
        if p.available_at > cutoff:
            continue
        key = (
            p.subject_ref.subject_id,
            p.source_id,
            p.source_record_id,
            p.observation_window,
        )
        old = groups.get(key)
        if old is None or p.available_at > old[0].available_at:
            groups[key] = [p]
        elif p.available_at == old[0].available_at and p.point_id not in {
            v.point_id for v in old
        }:
            old.append(p)
    return tuple(p for values in groups.values() for p in values)


def feed_coverage(builder, session, points, records, as_of):
    bindings = {
        b.feed_id: b
        for b in builder.bindings
        if b.validated_at <= session.decision_cutoff
    }
    rows = []
    for spec in builder.registry.feeds:
        binding = bindings.get(spec.feed_id)
        # Reuse the runtime's selection rules, including source/unit/status/window checks.
        selected = builder._select(
            spec, binding, session, points, session.decision_cutoff
        )
        source_day = selected.observation_session
        age = (
            builder.calendar.age_of_date(source_day, session.session_id)
            if source_day
            else None
        )
        attempts = [
            r
            for r in records
            if r["feed_id"] == spec.feed_id
            and session.closes_at
            <= datetime.fromisoformat(r["first_seen_at"])
            <= session.decision_cutoff
        ]
        later = [
            p
            for p in points
            if binding is not None
            and p.subject_ref == binding.subject_ref
            and p.source_record_id == spec.feed_id + ":" + session.session_id
            and session.decision_cutoff < p.available_at <= as_of
            and p.data_status is DataStatus.AVAILABLE
        ]
        rows.append(
            {
                "feed_id": spec.feed_id,
                "status": selected.status.value,
                "source_day": source_day,
                "source_age_sessions": age,
                "available_within_contract": selected.status is DataStatus.AVAILABLE,
                "age_zero_available": selected.status is DataStatus.AVAILABLE
                and age == 0,
                "selected_point_ids": [p.point_id for p in selected.points],
                "qualifiers": selected.qualifiers,
                "timely_fetch_attempts": len(attempts),
                "retry_or_poll_attempts": max(0, len(attempts) - 1),
                "http_failed_attempts": sum(
                    r["http_status"] != 200 or bool(r["error"]) for r in attempts
                ),
                "first_late_current_observation_at": min(
                    (p.available_at.isoformat() for p in later), default=None
                ),
            }
        )
    return rows


def coverage_report(store, protocol, pilot, clock, as_of):
    calendar = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    validate_pilot(pilot, calendar)
    if as_of.tzinfo is None:
        raise ValueError("aware watermark required")
    min_day = calendar.history(pilot["decision_sessions"][0], 273)[0].session_id
    builder, points, records, parsing = load_inputs(
        store, protocol, calendar, as_of, min_day, clock
    )
    complete = [
        calendar.get(day)
        for day in pilot["decision_sessions"]
        if calendar.get(day).decision_cutoff <= as_of
    ]
    history = []
    daily = []
    for session in complete:
        eligible = latest_at_cutoff(points, session.decision_cutoff)
        build = builder.build(session.session_id, eligible)
        # Verify compaction against the complete, un-compacted recorded prefix.
        original = builder.build(
            session.session_id,
            tuple(p for p in points if p.available_at <= session.decision_cutoff),
        )
        if original.snapshot.snapshot_id != build.snapshot.snapshot_id:
            raise ValueError("revision compaction replay mismatch")
        references = ReferenceBuilder(calendar).build(build, tuple(history))
        feeds = feed_coverage(builder, session, eligible, records, as_of)
        # Late arrivals are diagnostic only and cannot change the original snapshot.
        for row in feeds:
            row["first_late_current_observation_at"] = min(
                (
                    p.available_at.isoformat()
                    for p in points
                    if p.source_record_id == row["feed_id"] + ":" + session.session_id
                    and session.decision_cutoff < p.available_at <= as_of
                    and p.data_status is DataStatus.AVAILABLE
                ),
                default=None,
            )
        sensors = [
            {
                "sensor_id": m.sensor_id,
                "status": m.data_status.value,
                "qualifiers": m.qualifiers,
                "measurement_id": m.measurement_id,
            }
            for m in build.measurements
        ]
        S_sensors = tuple(sensor for _, members, _ in GROUPS for sensor, _ in members)
        S_measurements_complete = all(
            build.measurement(sensor).data_status is DataStatus.AVAILABLE
            and "LAGGED_INPUT" not in build.measurement(sensor).qualifiers
            for sensor in S_sensors
        )
        D_measurements_complete = all(
            build.measurement(sensor).data_status is DataStatus.AVAILABLE
            and "LAGGED_INPUT" not in build.measurement(sensor).qualifiers
            for sensor in PAIRS
        )
        required = [
            m
            for m in build.measurements
            if next(
                s for s in builder.registry.sensors if s.sensor_id == m.sensor_id
            ).required
        ]
        s_ready = all(
            next(f for f in feeds if f["feed_id"] == feed)["age_zero_available"]
            for feed in pilot["source_age_zero_S_feed_ids"]
        )
        daily.append(
            {
                "decision_session": session.session_id,
                "decision_cutoff": session.decision_cutoff.isoformat(),
                "snapshot_id": build.snapshot.snapshot_id,
                "active_required_available": sum(
                    m.data_status is DataStatus.AVAILABLE for m in required
                ),
                "active_required_expected": len(required),
                "state_vector_complete": all(
                    m.data_status is DataStatus.AVAILABLE for m in required
                ),
                "S_age_zero_inputs_complete": s_ready,
                "S_current_measurements_complete": S_measurements_complete,
                "D_current_measurements_complete": D_measurements_complete,
                "feeds": feeds,
                "sensors": sensors,
                "references": [
                    {
                        "configuration": r.reference_config_id,
                        "status": r.data_status.value,
                        "reference_id": r.reference_id,
                        "prior_usable": r.coverage.prior_usable,
                        "qualifiers": r.qualifiers,
                    }
                    for r in references
                ],
                "causal_revision_compaction": "PASS",
            }
        )
        history.append(build)
    n = len(daily)
    rates = {
        feed: (
            sum(
                next(f for f in day["feeds"] if f["feed_id"] == feed)[
                    "available_within_contract"
                ]
                for day in daily
            )
            / n
            if n
            else None
        )
        for feed in pilot["required_feed_ids"]
    }
    return {
        "task_id": "6B-2I-3",
        "as_of": as_of.isoformat(),
        "pilot_id": stable_content_hash(pilot),
        "clock_profile_id": stable_content_hash(clock),
        "completed_decisions": n,
        "planned_decisions": 20,
        "daily": daily,
        "required_feed_contract_coverage": rates,
        "complete_state_vector_coverage": (
            sum(d["state_vector_complete"] for d in daily) / n if n else None
        ),
        "S_current_measurement_coverage": (
            sum(d["S_current_measurements_complete"] for d in daily) / n if n else None
        ),
        "D_current_measurement_coverage": (
            sum(d["D_current_measurements_complete"] for d in daily) / n if n else None
        ),
        "S_age_zero_input_coverage": (
            sum(d["S_age_zero_inputs_complete"] for d in daily) / n if n else None
        ),
        "coverage_pilot_status": (
            "INSUFFICIENT_SAMPLE"
            if n < 20
            else (
                "COVERAGE_THRESHOLD_MET"
                if all(r >= 0.95 for r in rates.values())
                else "COVERAGE_THRESHOLD_FAILED"
            )
        ),
        "polling_job_events": (
            [read_job(p) for p in sorted((store.root / "jobs").glob("*.json"))]
            if (store.root / "jobs").exists()
            else []
        ),
        "source_clock_admission": clock["clock_admission"],
        "data_admission": "BLOCKED_DATA",
        "parsing": parsing,
        "note": "Coverage threshold alone is not clock/history/S/D/effectiveness admission. Missing consecutive days stay in the denominator. No forecast or production promotion.",
    }


def write_once(path, value):
    with path.open("xb") as stream:
        stream.write(encoded(value))


def read_job(path):
    sealed = json.loads(path.read_bytes())
    if hashlib.sha256(encoded(sealed["event"])).hexdigest() != sealed["sha256"]:
        raise ValueError("polling job journal changed")
    return sealed["event"]


def write_job(path, event):
    write_once(
        path, {"event": event, "sha256": hashlib.sha256(encoded(event)).hexdigest()}
    )


def tick(store, pilot, calendar, now, capture=capture_sources):
    jobs = store.root / "jobs"
    jobs.mkdir(exist_ok=True)
    results = []
    for day in pilot["decision_sessions"]:
        session = calendar.get(day)
        for offset in pilot["capture_offsets_after_close_minutes"]:
            scheduled = session.closes_at + timedelta(minutes=offset)
            path = jobs / (day + "-" + str(offset) + ".json")
            if path.exists():
                read_job(path)
                continue
            if now < scheduled:
                continue
            event = {
                "decision_session": day,
                "offset_minutes": offset,
                "scheduled_at": scheduled.isoformat(),
                "recorded_at": now.isoformat(),
            }
            if now > scheduled + timedelta(minutes=pilot["slot_grace_minutes"]):
                event["status"] = "MISSED"
            else:
                captured = capture(store)
                event.update(
                    status="CAPTURED",
                    capture_ids=[r["capture_id"] for r in captured],
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                now = datetime.now(timezone.utc)
            write_job(path, event)
            results.append(event)
        cutoff_marker = jobs / (day + "-cutoff.json")
        if cutoff_marker.exists():
            read_job(cutoff_marker)
        if now >= session.decision_cutoff and not cutoff_marker.exists():
            event = {
                "decision_session": day,
                "status": "CUTOFF_ELAPSED",
                "recorded_at": now.isoformat(),
            }
            write_job(cutoff_marker, event)
            results.append(event)
    return results


def save_report(store, report):
    directory = store.root / "coverage"
    directory.mkdir(exist_ok=True)
    path = directory / (hashlib.sha256(encoded(report)).hexdigest() + ".json")
    if not path.exists():
        write_once(path, report)
    elif path.read_bytes() != encoded(report):
        raise ValueError("coverage archive changed")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
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
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("research/sentinel/6b-2g-contracts/protocol.json"),
    )
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--capture-now", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    pilot, clock = load_configuration(args.pilot, args.clocks)
    raw = CaptureStore(args.store)
    store = ProfileStore(raw, clock)
    validate_clock_profile(clock, store)
    calendar = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    validate_pilot(pilot, calendar)
    with (store.root / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.capture_now:
            capture_sources(store)
        while True:
            now = datetime.now(timezone.utc)
            events = [] if args.report_only else tick(store, pilot, calendar, now)
            if not args.daemon or events:
                report = coverage_report(
                    store,
                    json.loads(args.protocol.read_text()),
                    pilot,
                    clock,
                    datetime.now(timezone.utc),
                )
                print(
                    json.dumps(
                        {
                            "report": str(save_report(store, report)),
                            "completed_decisions": report["completed_decisions"],
                            "status": report["coverage_pilot_status"],
                        }
                    ),
                    flush=True,
                )
            heartbeat = {
                "pid": os.getpid(),
                "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "pilot_id": stable_content_hash(pilot),
                "durability": "LOCAL_PROCESS_NOT_DURABLE_SCHEDULER",
            }
            temporary = store.root / "heartbeat.tmp"
            temporary.write_bytes(encoded(heartbeat))
            temporary.replace(store.root / "heartbeat.json")
            if (
                not args.daemon
                or now > calendar.get(pilot["decision_sessions"][-1]).decision_cutoff
            ):
                if args.daemon:
                    report = coverage_report(
                        store,
                        json.loads(args.protocol.read_text()),
                        pilot,
                        clock,
                        datetime.now(timezone.utc),
                    )
                    print(str(save_report(store, report)), flush=True)
                break
            time.sleep(20)


if __name__ == "__main__":
    main()
