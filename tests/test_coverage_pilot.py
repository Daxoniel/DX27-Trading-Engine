from datetime import date, datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.source_clocks import ProfileStore, clock_window
from dx27.adapters.sentinel.recorded_sources import (
    binding_for,
    normalize_capture,
    CORE,
    FRED_IDS,
)
from dx27.adapters.sentinel.coverage_pilot import (
    coverage_report,
    tick,
    validate_pilot,
    load_configuration,
)

ROOT = Path("research/sentinel/6b-2i-3-clock-coverage")


@pytest.fixture
def setup(tmp_path):
    calendar = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    raw = CaptureStore(tmp_path)
    evidence = raw.put(
        "clock_0_metadata",
        "official-clock-document",
        "https://example.test/clock",
        b"fixture",
        datetime(2026, 10, 8, 12, tzinfo=timezone.utc),
    )
    clock = json.loads((ROOT / "clock_profile.json").read_text())
    clock["evidence_capture_ids"] = [evidence["capture_id"]]
    return ProfileStore(raw, clock), clock, calendar


def fixture_data(store, calendar, feed, seen):
    if feed in ("spy", "rsp", "qqq", "iwm"):
        sessions = calendar.history("2026-10-08", 23)
        close = [100 + i + (i % 3) * 0.1 for i in range(23)]
        payload = {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "symbol": feed.upper(),
                            "currency": "USD",
                            "instrumentType": "ETF",
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": [int(s.opens_at.timestamp()) for s in sessions],
                        "indicators": {
                            "quote": [
                                {
                                    "open": close,
                                    "high": [v + 1 for v in close],
                                    "low": [v - 1 for v in close],
                                    "close": close,
                                    "volume": [1000] * 23,
                                }
                            ],
                            "adjclose": [{"adjclose": close}],
                        },
                    }
                ],
            }
        }
        return store.put(
            feed,
            "yahoo-chart-v8",
            "https://example.test",
            json.dumps(payload).encode(),
            seen,
        )
    if feed == "vix":
        return store.put(
            feed,
            "cboe-daily-csv",
            "https://example.test",
            b"DATE,OPEN,HIGH,LOW,CLOSE\n10/08/2026,20,21,19,20.2\n",
            seen,
        )
    series = FRED_IDS[feed]
    day = "2026-10-07" if feed == "hy_oas" else "2026-10-08"
    metadata = f'{series}<span class="series-meta-value-units">Percent</span><span class="series-meta-value-frequency">Daily</span>'.encode()
    store.put(
        feed + "_metadata",
        "fred-series-metadata",
        "https://example.test",
        metadata,
        seen,
    )
    return store.put(
        feed,
        "fred-public-csv",
        "https://example.test",
        f"observation_date,{series}\n{day},3.2\n".encode(),
        seen,
    )


def test_clocks_dst_early_close_and_closed_dates(setup):
    _, clock, calendar = setup
    assert clock_window("vix", "2026-10-08", calendar, clock).end.hour == 16
    assert (
        clock_window("vix", "2026-10-08", calendar, clock)
        .end.astimezone(timezone.utc)
        .hour
        == 20
    )
    assert (
        clock_window("vix", "2026-11-02", calendar, clock)
        .end.astimezone(timezone.utc)
        .hour
        == 21
    )
    assert clock_window("vix", "2026-11-27", calendar, clock) is None
    assert clock_window("ust_2y", "2026-10-10", calendar, clock) is None


def test_clock_evidence_does_not_backdate_bindings(setup):
    store, clock, calendar = setup
    record = store.put(
        "vix",
        "cboe-daily-csv",
        "https://example.test",
        b"DATE,OPEN,HIGH,LOW,CLOSE\n10/07/2026,20,21,19,20.2\n",
        datetime(2026, 10, 7, 21, tzinfo=timezone.utc),
    )
    raw = store.get(record["capture_id"])[1]
    binding, _ = binding_for("vix", record, raw, store, calendar, clock_profile=clock)
    assert binding.validated_at == datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="evidence unavailable"):
        binding_for(
            "vix",
            record,
            raw,
            store,
            calendar,
            datetime(2026, 10, 7, 22, tzinfo=timezone.utc),
            clock,
        )
    assert binding.observation_label_policy == "LOCAL_DATE_OF_END"
    points, _ = normalize_capture("vix", binding, record, raw, calendar, clock)
    assert points[0].published_at is None
    assert points[0].available_at == datetime(2026, 10, 7, 21, tzinfo=timezone.utc)


def test_preserves_old_profile_namespace(setup):
    store, clock, calendar = setup
    record = fixture_data(
        store, calendar, "vix", datetime(2026, 10, 8, 21, tzinfo=timezone.utc)
    )
    raw = store.get(record["capture_id"])[1]
    old, _ = binding_for("vix", record, raw, store.raw_store, calendar)
    new, _ = binding_for("vix", record, raw, store, calendar, clock_profile=clock)
    assert old.source_version == "recorded-source-profile-v1"
    assert old.binding_version != new.binding_version
    assert (
        store.raw_store.binding_record("vix")["profile"]["source_version"]
        == "recorded-source-profile-v1"
    )


def test_cutoff_coverage_keeps_missed_days_and_late_revisions(setup):
    store, clock, calendar = setup
    for feed in CORE:
        fixture_data(
            store, calendar, feed, datetime(2026, 10, 8, 21, tzinfo=timezone.utc)
        )
    pilot = json.loads((ROOT / "pilot_protocol.json").read_text())
    protocol = json.loads(
        Path("research/sentinel/6b-2g-contracts/protocol.json").read_text()
    )
    first = coverage_report(
        store, protocol, pilot, clock, datetime(2026, 10, 8, 22, tzinfo=timezone.utc)
    )
    assert first["completed_decisions"] == 1
    assert first["daily"][0]["active_required_available"] == 13
    assert first["daily"][0]["state_vector_complete"]
    assert not first["daily"][0]["S_age_zero_inputs_complete"]
    assert all(r == 1 for r in first["required_feed_contract_coverage"].values())
    assert first["coverage_pilot_status"] == "INSUFFICIENT_SAMPLE"
    # A late revision to the same observation cannot rewrite yesterday's state.
    raw = b"DATE,OPEN,HIGH,LOW,CLOSE\n10/08/2026,20,30,19,29\n"
    store.put(
        "vix",
        "cboe-daily-csv",
        "https://example.test",
        raw,
        datetime(2026, 10, 9, 23, tzinfo=timezone.utc),
    )
    later = coverage_report(
        store, protocol, pilot, clock, datetime(2026, 10, 9, 23, tzinfo=timezone.utc)
    )
    assert later["daily"][0]["snapshot_id"] == first["daily"][0]["snapshot_id"]
    assert later["completed_decisions"] == 2
    assert later["required_feed_contract_coverage"]["spy"] == 0.5
    assert later["complete_state_vector_coverage"] == 0.5
    assert later["daily"][1]["feeds"]
    assert later["data_admission"] == "BLOCKED_DATA"


def test_no_completed_cutoffs_has_null_coverage(setup):
    store, clock, _ = setup
    pilot = json.loads((ROOT / "pilot_protocol.json").read_text())
    protocol = json.loads(
        Path("research/sentinel/6b-2g-contracts/protocol.json").read_text()
    )
    report = coverage_report(
        store, protocol, pilot, clock, datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    )
    assert report["completed_decisions"] == 0
    assert report["S_age_zero_input_coverage"] is None
    assert all(v is None for v in report["required_feed_contract_coverage"].values())


def test_schedule_is_idempotent_and_missed_slots_not_fetched(setup):
    store, _, calendar = setup
    pilot = json.loads((ROOT / "pilot_protocol.json").read_text())
    day = pilot["decision_sessions"][0]
    session = calendar.get(day)
    calls = []

    def fetch(_):
        calls.append(True)
        return []

    now = session.closes_at + timedelta(minutes=30)
    events = tick(store, pilot, calendar, now, fetch)
    assert events[0]["status"] == "MISSED" and not calls
    assert tick(store, pilot, calendar, now, fetch) == []
    tick(store, pilot, calendar, session.closes_at + timedelta(minutes=60), fetch)
    assert len(calls) == 1


def test_locked_protocol_and_denominator(setup):
    _, _, calendar = setup
    pilot, _ = load_configuration(
        ROOT / "pilot_protocol.json", ROOT / "clock_profile.json"
    )
    validate_pilot(pilot, calendar)
    changed = copy.deepcopy(pilot)
    changed["decision_sessions"].pop(1)
    with pytest.raises(ValueError, match="consecutive"):
        validate_pilot(changed, calendar)
    changed = copy.deepcopy(pilot)
    changed["operational_coverage_min"] = 0.90
    with pytest.raises(ValueError, match="acceptance"):
        validate_pilot(changed, calendar)


def test_poll_journal_tampering_is_rejected(setup):
    store, _, calendar = setup
    pilot = json.loads((ROOT / "pilot_protocol.json").read_text())
    session = calendar.get(pilot["decision_sessions"][0])
    now = session.closes_at + timedelta(minutes=30)
    tick(store, pilot, calendar, now, lambda _: [])
    path = next((store.root / "jobs").glob("*.json"))
    event = json.loads(path.read_bytes())
    event["event"]["status"] = "CAPTURED"
    path.write_text(json.dumps(event))
    with pytest.raises(ValueError, match="journal changed"):
        tick(store, pilot, calendar, now, lambda _: [])


def test_http_failures_and_retries_are_not_data_coverage(setup):
    store, clock, calendar = setup
    for feed in CORE:
        fixture_data(
            store, calendar, feed, datetime(2026, 10, 8, 21, tzinfo=timezone.utc)
        )
    store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test",
        b"error",
        datetime(2026, 10, 8, 20, 30, tzinfo=timezone.utc),
        status=503,
        error="HTTP_ERROR",
    )
    pilot = json.loads((ROOT / "pilot_protocol.json").read_text())
    protocol = json.loads(
        Path("research/sentinel/6b-2g-contracts/protocol.json").read_text()
    )
    report = coverage_report(
        store, protocol, pilot, clock, datetime(2026, 10, 8, 22, tzinfo=timezone.utc)
    )
    spy = next(f for f in report["daily"][0]["feeds"] if f["feed_id"] == "spy")
    assert spy["http_failed_attempts"] == 1 and spy["retry_or_poll_attempts"] == 1
    assert spy["available_within_contract"]
    assert any(r["status"] == "SOURCE_ERROR" for r in report["parsing"])
