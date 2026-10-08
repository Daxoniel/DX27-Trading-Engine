"""Prospective source clock profiles; never infer row publication timestamps."""

from datetime import datetime, time, timedelta
from pathlib import Path
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import ObservationWindow
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


class ProfileStore(CaptureStore):
    """One raw journal, isolated bindings/configuration for each clock version."""

    def __init__(self, raw_store, profile):
        self.raw_store = raw_store
        self.profile_id = stable_content_hash(profile)
        super().__init__(raw_store.root / "profiles" / self.profile_id)

    def get(self, capture_id):
        return self.raw_store.get(capture_id)

    def put(self, *args, **kwargs):
        return self.raw_store.put(*args, **kwargs)

    def records(self):
        return self.raw_store.records()


def validate_clock_profile(profile, store):
    if profile["schema_version"] != "sentinel-source-clocks-v1":
        raise ValueError("unknown clock profile")
    if set(profile["regular_session_bounds"]) != {"vix", "ust_2y", "ust_10y"}:
        raise ValueError("unexpected enabled source clocks")
    expected = {"vix": "16:16:00", "ust_2y": "16:00:00", "ust_10y": "16:00:00"}
    if profile["regular_session_bounds"] != expected:
        raise ValueError("unsupported observation completion bounds")
    if not profile["evidence_capture_ids"]:
        raise ValueError("clock evidence missing")
    records = [store.get(i)[0] for i in profile["evidence_capture_ids"]]
    if any(
        r["http_status"] != 200
        or r["error"]
        or r["source_id"] != "official-clock-document"
        for r in records
    ):
        raise ValueError("invalid clock evidence capture")
    return max(datetime.fromisoformat(r["first_seen_at"]) for r in records)


def clock_window(feed, day, calendar, profile):
    """Return None for unverified early-close/closed dates, not a guessed clock."""
    start = datetime.fromisoformat(day).replace(tzinfo=NY)
    if feed not in profile["regular_session_bounds"]:
        return ObservationWindow(start, start + timedelta(days=1), "1d")
    try:
        session = calendar.get(day)
    except ValueError:
        return None
    if session.closes_at.astimezone(NY).time() != time(16):
        return None
    hour, minute, second = map(int, profile["regular_session_bounds"][feed].split(":"))
    return ObservationWindow(
        start, start.replace(hour=hour, minute=minute, second=second), "1d"
    )
