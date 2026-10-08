"""Distinguish decision periods from raw history needed for causal warmup."""

from datetime import date
from dx27.adapters.calendars.xnys import load_xnys_calendar


def history_requirements(
    protocol: dict, decision_period_start="2005-01-01", decision_period_end="2026-09-30"
):
    start = date.fromisoformat(decision_period_start)
    if decision_period_end < decision_period_start:
        raise ValueError("decision end precedes start")
    calendar = load_xnys_calendar(date(start.year - 2, 1, 1), date(start.year, 12, 31))
    first = next(s for s in calendar.sessions if s.session_id >= decision_period_start)
    index = calendar.sessions.index(first)
    lookbacks = {f["feed_id"]: 0 for f in protocol["feeds"]}
    for sensor in protocol["sensors"]:
        for feed in sensor["input_feed_ids"]:
            lookbacks[feed] = max(lookbacks[feed], sensor["lookback_sessions"])
    prior = max(
        protocol["reference_research"]["percentile"]["window_sessions"],
        protocol["reference_research"]["relationship_window_sessions"],
    )
    rows = {}
    for feed, lookback in lookbacks.items():
        if index < prior + lookback:
            raise ValueError("calendar bounds do not cover full raw warmup")
        rows[feed] = {
            "raw_history_start_required": calendar.sessions[
                index - prior - lookback
            ].session_id,
            "prior_measurement_sessions": prior,
            "measurement_lookback_sessions": lookback,
            "raw_session_intervals_before_first_decision": prior + lookback,
            "minimum_price_points_in_measurement": lookback + 1 if lookback else None,
        }
    return {
        "decision_period_start": decision_period_start,
        "first_decision_session": first.session_id,
        "decision_period_end": decision_period_end,
        "raw_history_start_required": min(
            r["raw_history_start_required"] for r in rows.values()
        ),
        "prior_measurement_start": calendar.sessions[index - prior].session_id,
        "calendar_version": calendar.calendar_version,
        "policy": "Full 252 prior measurement sessions; price inputs also need each measurement lookback. This is not historical availability evidence.",
        "per_feed": rows,
    }
