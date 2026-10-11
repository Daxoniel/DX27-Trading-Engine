"""Sealed, single-vintage ETF price inputs for an experimental report forecast.

This adapter neither admits research data nor changes the pilot's clocks. It
rechecks source identity and completed daily bars at the report's actual capture
watermark; an earlier successful capture cannot replace a newer failed attempt.
"""

from datetime import datetime
import json
import math
from zoneinfo import ZoneInfo

from dx27.adapters.sentinel.recorded_sources import binding_for, normalize_capture
from dx27.intelligence.sentinel.models import DataStatus
from dx27.intelligence.sentinel.session_calendar import utc


FORECAST_FEEDS = ("spy", "rsp", "qqq", "iwm")


def extract_price_context(store, report, calendar, context_sessions=253):
    """Return aligned adjusted closes from each feed's latest eligible capture.

    ``context_sessions`` counts closes, not returns: 253 closes provide 252
    returns. Source/data shortages are per-feed abstentions. Capture or binding
    integrity failures propagate as hard errors rather than being hidden as an
    ordinary unavailable source. No raw data is written outside the input store.
    """
    if (store.root / "configuration.json").exists() or (
        store.root / "profiles"
    ).exists():
        raise ValueError("forecast inputs require a separate non-pilot store")
    if (
        isinstance(context_sessions, bool)
        or not isinstance(context_sessions, int)
        or context_sessions < 2
    ):
        raise ValueError("context_sessions must be an integer of at least two")
    try:
        as_of = utc(datetime.fromisoformat(report["as_of"]))
        origin = calendar.get(report["session_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("valid aware report watermark and origin required") from exc
    watermark_day = as_of.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if not calendar.valid_from <= watermark_day <= calendar.valid_through:
        raise ValueError("forecast watermark outside calendar bounds")
    if report.get("original_calendar_version", calendar.calendar_version) != calendar.calendar_version:
        raise ValueError("forecast calendar differs from the observation calendar")
    if origin.closes_at > as_of:
        raise ValueError("forecast origin session is not complete at the watermark")
    completed = [s for s in calendar.sessions if s.closes_at <= as_of]
    if completed[-1].session_id != origin.session_id:
        raise ValueError("forecast origin is not the latest completed session")

    history = calendar.history(origin.session_id, context_sessions)
    result = {
        "origin_session": origin.session_id,
        "context_sessions": context_sessions,
        "session_ids": [s.session_id for s in history],
        "prices": {},
        "sources": {},
        "unavailable": {},
    }
    if len(history) < context_sessions:
        result["unavailable"] = {
            feed: "INSUFFICIENT_CALENDAR_CONTEXT" for feed in FORECAST_FEEDS
        }
        return result

    # records() verifies every journal seal and payload before source failures
    # can be treated as an abstention. Future records remain ineligible inputs.
    records = sorted(
        (
            record
            for record in store.records()
            if utc(datetime.fromisoformat(record["first_seen_at"])) <= as_of
        ),
        key=lambda record: (
            utc(datetime.fromisoformat(record["first_seen_at"])),
            record["capture_id"],
        ),
    )
    latest = {record["feed_id"]: record for record in records}
    expected_ids = set(result["session_ids"])
    sessions_by_close = {session.closes_at: session.session_id for session in history}
    source_results = report.get("source_results", [])
    for feed in FORECAST_FEEDS:
        record = latest.get(feed)
        if record is None:
            result["unavailable"][feed] = "NO_ELIGIBLE_CAPTURE"
            continue
        if record["http_status"] != 200 or record["error"]:
            result["unavailable"][feed] = "LATEST_FETCH_FAILED"
            continue
        reported = [
            source
            for source in source_results
            if source.get("feed_id") == feed and source.get("is_latest_attempt") is True
        ]
        if (
            len(reported) != 1
            or reported[0].get("capture_id") != record["capture_id"]
            or reported[0].get("used_for_report") is not True
            or reported[0].get("status") != "NORMALIZED_DESCRIPTIVE"
        ):
            result["unavailable"][feed] = "REPORT_SOURCE_NOT_CURRENT_AND_USABLE"
            continue

        # Perform existing integrity checks outside the provider-data exception
        # handler. A damaged binding/payload must abort instead of going stale.
        existing_binding = store.binding_record(feed)
        if existing_binding is not None and utc(
            datetime.fromisoformat(existing_binding["validated_at"])
        ) > as_of:
            result["unavailable"][feed] = "BINDING_VALIDATION_AFTER_WATERMARK"
            continue
        record, raw = store.get(record["capture_id"])
        try:
            binding, _ = binding_for(feed, record, raw, store, calendar, as_of=as_of)
            points, counts = normalize_capture(
                feed,
                binding,
                record,
                raw,
                calendar,
                min_observation_date=history[0].session_id,
            )
            if counts["source_error_rows"]:
                raise ValueError("completed source rows contain invalid values")
            by_session = {}
            seen = utc(datetime.fromisoformat(record["first_seen_at"]))
            for point in points:
                if (
                    point.first_seen_at > as_of
                    or point.observation_window.end > min(as_of, seen)
                ):
                    continue
                # ETF windows are validated against exact exchange sessions;
                # match the close timestamp rather than assuming UTC labels.
                session_id = sessions_by_close.get(point.observation_window.end)
                if session_id is None:
                    continue
                if (
                    point.data_status is not DataStatus.AVAILABLE
                    or isinstance(point.value, bool)
                    or not isinstance(point.value, (int, float))
                    or not math.isfinite(point.value)
                    or point.value <= 0
                ):
                    raise ValueError("context contains an unavailable price")
                if session_id in by_session:
                    raise ValueError("context contains duplicate sessions")
                by_session[session_id] = float(point.value)
            if set(by_session) != expected_ids:
                result["unavailable"][feed] = "INCOMPLETE_CONTIGUOUS_CONTEXT"
                continue
        except (
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            result["unavailable"][feed] = "INVALID_LATEST_CONTEXT: " + str(exc)
            continue
        result["prices"][feed] = [by_session[session.session_id] for session in history]
        result["sources"][feed] = {
            key: record[key]
            for key in ("capture_id", "payload_sha256", "first_seen_at")
        }
    return result
