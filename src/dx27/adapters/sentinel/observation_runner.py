"""One-shot latest-vintage observation report, isolated from the frozen pilot."""

import argparse
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore, encoded
from dx27.adapters.sentinel.recorded_runner import capture_sources
from dx27.adapters.sentinel.recorded_sources import binding_for, normalize_capture
from dx27.intelligence.sentinel.market_state import MarketStateBuilder, SensorRegistry
from dx27.intelligence.sentinel.sensor_contracts import VintageMode
from dx27.intelligence.sentinel.session_calendar import (
    SessionCalendar,
    TradingSession,
    utc,
)
from dx27.intelligence.sentinel.state_projection import project_market_now


def observation_projection(build, bindings):
    """Expose provider observation labels separately from period-end timestamps."""
    projection = project_market_now(build)["market_now"]
    by_measurement = {
        m.measurement_id: m for m in (*build.measurements, *build.sector_context)
    }
    by_point = {p.point_id: p for p in build.input_points}
    by_subject = {b.subject_ref.subject_id: b for b in bindings}
    for entries in projection.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or "measurement_ref" not in entry:
                continue
            measurement = by_measurement[entry["measurement_ref"]]
            points = [by_point[i] for i in measurement.input_point_ids]
            if not points:
                continue
            end = max(p.observation_window.end for p in points)
            labels = set()
            for point in points:
                if point.observation_window.end != end:
                    continue
                policy = by_subject[
                    point.subject_ref.subject_id
                ].observation_label_policy
                zone = (
                    timezone.utc
                    if policy.startswith("UTC_DATE")
                    else ZoneInfo("America/New_York")
                )
                label_end = point.observation_window.end.astimezone(zone)
                if policy.endswith("BEFORE_EXCLUSIVE_END"):
                    label_end -= timedelta(microseconds=1)
                labels.add(label_end.date().isoformat())
            entry["state"]["observation_label"] = (
                next(iter(labels)) if len(labels) == 1 else None
            )
            entry["state"]["captured_at"] = max(
                p.first_seen_at for p in points
            ).isoformat()
    return projection


@dataclass(frozen=True)
class DescriptiveSession(TradingSession):
    """An observation date evaluated at the actual capture watermark, not backdated."""

    __canonical_type_id__ = "sentinel.latest_vintage_descriptive_session"
    __canonical_type_version__ = "1"

    report_as_of: datetime

    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(self, "report_as_of", utc(self.report_as_of))
        if self.report_as_of < self.closes_at:
            raise ValueError("descriptive report cannot use an incomplete session")

    @property
    def decision_cutoff(self):
        return self.report_as_of


def descriptive_calendar(calendar, as_of):
    """Give a separate identity to same-vintage historical comparisons."""
    as_of = utc(as_of)
    day = as_of.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if not calendar.valid_from <= day <= calendar.valid_through:
        raise ValueError("observation watermark outside calendar bounds")
    sessions = tuple(
        DescriptiveSession(s.session_id, s.opens_at, s.closes_at, as_of)
        for s in calendar.sessions
        if s.closes_at <= as_of
    )
    if not sessions:
        raise ValueError("no completed session at observation watermark")
    return SessionCalendar(
        calendar.source_id,
        "latest-vintage-descriptive-v1:" + calendar.calendar_version,
        calendar.valid_from,
        day,
        sessions,
    )


def build_report(store, protocol, as_of, calendar=None):
    """Reuse existing measurements; never certify historical availability or efficacy."""
    if (store.root / "configuration.json").exists() or (
        store.root / "profiles"
    ).exists():
        raise ValueError("observation reports require a separate non-pilot store")
    as_of = utc(as_of)
    original = calendar or load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    descriptive = descriptive_calendar(original, as_of)
    records = sorted(
        (
            r
            for r in store.records()
            if datetime.fromisoformat(r["first_seen_at"]) <= as_of
        ),
        key=lambda r: (datetime.fromisoformat(r["first_seen_at"]), r["capture_id"]),
    )
    latest_attempts = {r["feed_id"]: r for r in records}
    bindings, points_by_feed, source_results, historical_successes = {}, {}, [], {}
    for record in records:
        feed = record["feed_id"]
        if feed.endswith("_metadata"):
            continue
        result = {
            k: record[k]
            for k in (
                "feed_id",
                "source_id",
                "first_seen_at",
                "http_status",
                "capture_id",
                "url",
                "payload_sha256",
                "published_at",
                "publication_evidence",
            )
        }
        latest = latest_attempts[feed]
        result.update(
            is_latest_attempt=record["capture_id"] == latest["capture_id"],
            latest_attempt_at=latest["first_seen_at"],
            latest_attempt_capture_id=latest["capture_id"],
        )
        metadata = latest_attempts.get(feed + "_metadata")
        if metadata is not None:
            result.update(
                latest_metadata_attempt_at=metadata["first_seen_at"],
                latest_metadata_attempt_capture_id=metadata["capture_id"],
                latest_metadata_http_status=metadata["http_status"],
            )
        raw = None
        try:
            _, raw = store.get(record["capture_id"])
            binding, qualifiers = binding_for(
                feed,
                record,
                raw,
                store,
                original,
                as_of=as_of,
                # A failed/latest invalid units response cannot be masked by a
                # successful metadata capture from an earlier attempt.
                metadata_records=(() if metadata is None else (metadata,)),
            )
            normalized, counts = normalize_capture(
                feed,
                binding,
                record,
                raw,
                original,
                min_observation_date=original.history(
                    descriptive.sessions[-1].session_id, 64
                )[0].session_id,
            )
            if not normalized:
                raise ValueError(
                    "no eligible completed observations in latest response"
                )
            if counts["source_error_rows"]:
                raise ValueError(
                    "captured completed observations contain source errors"
                )
            bindings[feed] = binding
            points_by_feed.setdefault(feed, []).extend(
                replace(p, vintage_mode=VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY)
                for p in normalized
            )
            result.update(
                status="NORMALIZED_DESCRIPTIVE",
                qualifiers=list(qualifiers),
                normalization=counts,
            )
        except (
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            json.JSONDecodeError,
        ) as exc:
            result.update(status="SOURCE_ERROR", reason=str(exc))
            # A later units-validation failure must not erase evidence that an
            # earlier payload was valid with the metadata then available. This
            # is provenance only: no recovered points enter the current report.
            prior_metadata = next(
                (
                    r
                    for r in reversed(records)
                    if metadata is not None
                    and r["feed_id"] == feed + "_metadata"
                    and datetime.fromisoformat(r["first_seen_at"])
                    < datetime.fromisoformat(metadata["first_seen_at"])
                    and r["http_status"] == 200
                    and not r["error"]
                ),
                None,
            )
            if (
                raw is not None
                and prior_metadata is not None
                and datetime.fromisoformat(record["first_seen_at"])
                < datetime.fromisoformat(metadata["first_seen_at"])
            ):
                try:
                    old_binding, _ = binding_for(
                        feed,
                        record,
                        raw,
                        store,
                        original,
                        as_of=as_of,
                        metadata_records=(prior_metadata,),
                    )
                    old_points, old_counts = normalize_capture(
                        feed,
                        old_binding,
                        record,
                        raw,
                        original,
                        min_observation_date=original.history(
                            descriptive.sessions[-1].session_id, 64
                        )[0].session_id,
                    )
                    if old_points and not old_counts["source_error_rows"]:
                        historical_successes[feed] = result
                        result["historical_success_metadata_capture_id"] = (
                            prior_metadata["capture_id"]
                        )
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError,
                    json.JSONDecodeError,
                ):
                    pass
        source_results.append(result)
    latest_results = {r["feed_id"]: r for r in source_results if r["is_latest_attempt"]}
    failed_feeds = sorted(
        feed
        for feed, result in latest_results.items()
        if result["status"] == "SOURCE_ERROR"
    )
    for feed in failed_feeds:
        # Preserve the raw journal, but never silently substitute an earlier
        # success for the latest failed fetch in either compared date.
        bindings.pop(feed, None)
        points_by_feed.pop(feed, None)
    last_successes = {
        r["feed_id"]: r
        for r in source_results
        if r["status"] == "NORMALIZED_DESCRIPTIVE"
    }
    for feed, historical in historical_successes.items():
        success = last_successes.get(feed)
        if success is None or datetime.fromisoformat(
            historical["first_seen_at"]
        ) > datetime.fromisoformat(success["first_seen_at"]):
            last_successes[feed] = historical
    for result in source_results:
        success = last_successes.get(result["feed_id"])
        result.update(
            used_for_report=result["feed_id"] not in failed_feeds
            and result["status"] == "NORMALIZED_DESCRIPTIVE",
            last_success_capture_id=success["capture_id"] if success else None,
            last_success_at=success["first_seen_at"] if success else None,
        )
    points = tuple(p for feed_points in points_by_feed.values() for p in feed_points)
    builder = MarketStateBuilder(
        SensorRegistry.from_protocol(protocol),
        descriptive,
        tuple(bindings.values()),
        VintageMode.LATEST_VINTAGE_DESCRIPTIVE_ONLY,
    )
    current_session = descriptive.sessions[-1]
    previous_session = (
        descriptive.sessions[-2] if len(descriptive.sessions) > 1 else None
    )
    # Same capture-vintage for BOTH dates. This is not yesterday's issued report.
    history = [
        {
            "session_id": s.session_id,
            "market_now": observation_projection(
                builder.build(s.session_id, tuple(points)), tuple(bindings.values())
            ),
        }
        for s in descriptive.sessions[-21:]
    ]
    current = history[-1]["market_now"]
    previous = history[-2]["market_now"] if previous_session else None
    return {
        "schema_version": "sentinel-observation-v1",
        "task_id": "6B-2H-1",
        "report_kind": "LATEST_VINTAGE_DESCRIPTIVE_ONLY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "session_id": current_session.session_id,
        "previous_session_id": (
            previous_session.session_id if previous_session else None
        ),
        "market_now": current,
        "previous_market_now": previous,
        "history": history,
        "comparison_policy": "SAME_CAPTURE_VINTAGE_NOT_HISTORICAL_KNOWN",
        "calendar_version": descriptive.calendar_version,
        "original_calendar_version": original.calendar_version,
        "source_results": source_results,
        "freshness_status": (
            "DEGRADED_LATEST_FETCH_FAILED"
            if failed_feeds
            else "LATEST_ATTEMPTS_SUCCEEDED"
        ),
        "latest_fetch_failed_feeds": failed_feeds,
        "input_capture_ids": [r["capture_id"] for r in records],
        "admission_status": "BLOCKED_DATA",
        "production_enabled": False,
        "predictive_effectiveness": "NOT_TESTED",
        "historical_availability": "NOT_CERTIFIED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store",
        type=Path,
        required=True,
        help="Dedicated observation captures; never the Windows pilot store",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("research/sentinel/6b-2g-contracts/protocol.json"),
    )
    parser.add_argument("--replay-only", action="store_true")
    args = parser.parse_args()
    if (args.store / "configuration.json").exists() or (
        args.store / "profiles"
    ).exists():
        raise ValueError("observation reports require a separate non-pilot store")
    marker = args.store / "observation-profile.json"
    if args.store.exists() and any(args.store.iterdir()) and not marker.exists():
        raise ValueError(
            "use a new observation store; existing unmarked stores are refused"
        )
    store = CaptureStore(args.store)
    profile = {
        "schema_version": "sentinel-observation-store-v1",
        "purpose": "LATEST_VINTAGE_DESCRIPTIVE_ONLY",
    }
    if not marker.exists():
        with marker.open("xb") as stream:
            stream.write(encoded(profile))
    elif json.loads(marker.read_bytes()) != profile:
        raise ValueError("observation store profile mismatch")
    if not args.replay_only:
        capture_sources(store)
    report = build_report(
        store, json.loads(args.protocol.read_bytes()), datetime.now(timezone.utc)
    )
    from dx27.adapters.sentinel.observation_report import render_html, render_markdown

    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (args.output / "市场观察.html").write_text(render_html(report), encoding="utf-8")
    (args.output / "市场观察.md").write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "session": report["session_id"],
                "report": str(args.output / "市场观察.html"),
                "source_results": [
                    (r["feed_id"], r["status"]) for r in report["source_results"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
