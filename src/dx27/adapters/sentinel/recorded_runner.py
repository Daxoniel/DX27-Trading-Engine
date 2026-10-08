"""One-shot real capture and causal replay. No scheduler or production promotion."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore, encoded
from dx27.adapters.sentinel.recorded_sources import (
    source_requests,
    binding_for,
    normalize_capture,
    reference_ids,
)
from dx27.intelligence.sentinel.market_state import SensorRegistry, MarketStateBuilder
from dx27.intelligence.sentinel.research.composite_reference import ReferenceBuilder
from dx27.intelligence.sentinel.state_projection import project_market_now
from dx27.intelligence.sentinel.research.history_requirements import (
    history_requirements,
)


def capture_sources(store):
    def fetch(request):
        feed, source, url = request
        status = 0
        raw = b""
        content_type = ""
        error = None
        try:
            with urlopen(
                Request(
                    url, headers={"User-Agent": "Mozilla/5.0 Sentinel research capture"}
                ),
                timeout=45,
            ) as response:
                raw = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as exc:
            status = exc.code
            raw = exc.read()
            error = "HTTP_ERROR"
        except Exception as exc:
            error = type(exc).__name__
        # Actual response completion, never HTTP Date, a bar label or nominal vintage.
        return store.put(
            feed,
            source,
            url,
            raw,
            datetime.now(timezone.utc),
            status=status,
            content_type=content_type,
            error=error,
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        return tuple(pool.map(fetch, source_requests()))


def completed_session(calendar, as_of, requested=None):
    if as_of.tzinfo is None:
        raise ValueError("aware replay watermark required")
    if requested:
        session = calendar.get(requested)
        if session.decision_cutoff > as_of:
            raise ValueError("decision cutoff has not completed")
        return session
    return next(s for s in reversed(calendar.sessions) if s.decision_cutoff <= as_of)


def replay(store, protocol, as_of, requested=None):
    calendar = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    pin = {
        "calendar_version": calendar.calendar_version,
        "protocol_digest": SensorRegistry.from_protocol(protocol).protocol_digest,
    }
    path = store.root / "configuration.json"
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(encoded(pin))
    if json.loads(path.read_bytes()) != pin:
        raise ValueError("pinned calendar/protocol changed")
    for binding_path in (store.root / "bindings").glob("*.json"):
        store.binding_record(
            binding_path.stem
        )  # Integrity failures abort replay, not merely a degraded feed.
    session = completed_session(calendar, as_of, requested)
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
    reports = []
    for record in records:
        feed = record["feed_id"]
        if feed.endswith("_metadata"):
            continue
        report = {
            "capture_id": record["capture_id"],
            "feed_id": feed,
            "first_seen_at": record["first_seen_at"],
            "payload_sha256": record["payload_sha256"],
            "http_status": record["http_status"],
            "reference_ids": reference_ids(feed),
        }
        try:
            raw = store.get(record["capture_id"])[1]
            binding, qualifiers = binding_for(feed, record, raw, store, calendar, as_of)
            normalized, counts = normalize_capture(feed, binding, record, raw, calendar)
            bindings[feed] = binding
            points.extend(normalized)
            report.update(
                status="RESEARCH_PROFILE_VALIDATED", qualifiers=qualifiers, **counts
            )
        except (
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            json.JSONDecodeError,
        ) as exc:
            report.update(status="SOURCE_ERROR", reason=str(exc))
        reports.append(report)
    builder = MarketStateBuilder(
        SensorRegistry.from_protocol(protocol), calendar, tuple(bindings.values())
    )
    build = builder.build(session.session_id, tuple(points))
    prefix = tuple(p for p in points if p.available_at <= session.decision_cutoff)
    prefix_build = builder.build(session.session_id, prefix)
    if build.snapshot.snapshot_id != prefix_build.snapshot.snapshot_id:
        raise ValueError("causal prefix replay mismatch")
    earliest = min(
        (datetime.fromisoformat(r["first_seen_at"]) for r in records), default=as_of
    )
    monitored = [s for s in calendar.sessions if earliest <= s.decision_cutoff <= as_of]
    history = tuple(
        builder.build(s.session_id, tuple(points))
        for s in monitored
        if s.session_id < session.session_id
    )
    references = ReferenceBuilder(calendar).build(build, history)
    projection = project_market_now(build)
    report = {
        "task_id": "6B-2I-2",
        "as_of": as_of.isoformat(),
        "decision_session": session.session_id,
        "decision_cutoff": session.decision_cutoff.isoformat(),
        "calendar_version": calendar.calendar_version,
        "protocol_digest": pin["protocol_digest"],
        "snapshot_id": build.snapshot.snapshot_id,
        "snapshot_status": projection["market_now"]["status"],
        "snapshot_coverage": projection["market_now"]["coverage"],
        "capture_count": len(records),
        "source_results": reports,
        "normalized_points": len(points),
        "cutoff_eligible_points": len(prefix),
        "causal_prefix_replay": "PASS",
        "completed_monitored_decisions": len(monitored),
        "operating_coverage": None,
        "admission_status": "BLOCKED_DATA",
        "references": [
            {
                "reference_id": r.reference_id,
                "configuration": r.reference_config_id,
                "status": r.data_status.value,
                "qualifiers": r.qualifiers,
            }
            for r in references
        ],
        "note": "Research profiles only. No operating coverage approval. Unknown publication times remain null. Bootstrap snapshots preceding first capture are not monitoring failures.",
    }
    return report, projection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("research/sentinel/6b-2g-contracts/protocol.json"),
    )
    parser.add_argument("--replay-only", action="store_true")
    parser.add_argument("--decision-session")
    args = parser.parse_args()
    store = CaptureStore(args.store)
    if not args.replay_only:
        capture_sources(store)
    report, projection = replay(
        store,
        json.loads(args.protocol.read_text()),
        datetime.now(timezone.utc),
        args.decision_session,
    )
    run_id = hashlib.sha256(encoded(report)).hexdigest()
    output = store.root / "runs" / run_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_bytes(encoded(report))
    (output / "market_now.json").write_bytes(encoded(projection))
    print(
        json.dumps(
            {
                "report": str(output / "report.json"),
                "status": report["snapshot_status"],
                "admission": report["admission_status"],
                "captures": report["capture_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
