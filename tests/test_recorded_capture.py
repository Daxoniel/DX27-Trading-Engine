from datetime import date, datetime, timezone
import json
import pytest
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.recorded_sources import binding_for, normalize_capture
from dx27.adapters.sentinel.recorded_runner import replay, completed_session
from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.intelligence.sentinel.research.history_requirements import (
    history_requirements,
)


@pytest.fixture
def calendar():
    return load_xnys_calendar(date(2026, 9, 1), date(2026, 10, 31))


def put(store, feed, raw, seen):
    return store.put(feed, "fred-public-csv", "https://example.test", raw, seen)


def test_exclusive_create_and_payload_tamper(tmp_path):
    store = CaptureStore(tmp_path)
    seen = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    record = put(store, "hy_oas", b"abc", seen)
    with pytest.raises(FileExistsError):
        put(store, "hy_oas", b"abc", seen)
    (tmp_path / "captures" / record["capture_id"] / "payload.bin").write_bytes(b"xyz")
    with pytest.raises(ValueError, match="payload changed"):
        store.get(record["capture_id"])


def test_unknown_publication_stable_binding_and_partial_date(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    seen = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    raw = b"observation_date,BAMLH0A0HYM2\n2026-10-06,3.2\n2026-10-07,3.1\n"
    record = put(store, "hy_oas", raw, seen)
    with pytest.raises(ValueError, match="metadata not captured"):
        binding_for("hy_oas", record, raw, store, calendar)
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test",
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span><span class="series-meta-value-frequency">Daily</span>',
        seen,
    )
    binding, _ = binding_for("hy_oas", record, raw, store, calendar)
    points, counts = normalize_capture("hy_oas", binding, record, raw, calendar)
    assert len(points) == 1 and counts["incomplete_observations_excluded"] == 1
    assert points[0].published_at is None and points[0].available_at == seen
    assert points[0].value == 320
    later = datetime(2026, 10, 8, 18, tzinfo=timezone.utc)
    second = put(store, "hy_oas", raw, later)
    same, _ = binding_for("hy_oas", second, raw, store, calendar)
    assert same.binding_version == binding.binding_version
    revised, _ = normalize_capture("hy_oas", same, second, raw, calendar)
    assert revised[0].revision_id == points[0].revision_id
    assert revised[0].available_at > points[0].available_at
    path = tmp_path / "bindings" / "hy_oas.json"
    sealed = json.loads(path.read_text())
    sealed["record"]["validated_at"] = later.isoformat()
    path.write_text(json.dumps(sealed))
    with pytest.raises(ValueError, match="binding record changed"):
        store.binding_record("hy_oas")


def test_future_decision_rejected(calendar):
    with pytest.raises(ValueError, match="not completed"):
        completed_session(
            calendar, datetime(2026, 10, 7, 18, tzinfo=timezone.utc), "2026-10-07"
        )


def test_history_boundaries():
    protocol = json.load(open("research/sentinel/6b-2g-contracts/protocol.json"))
    requirement = history_requirements(protocol)
    assert requirement["first_decision_session"] == "2005-01-03"
    assert requirement["prior_measurement_start"] == "2004-01-02"
    assert requirement["per_feed"]["spy"]["raw_history_start_required"] == "2003-12-03"
    assert (
        requirement["per_feed"]["hy_oas"]["raw_history_start_required"] == "2004-01-02"
    )


def test_bootstrap_does_not_backdate(tmp_path):
    store = CaptureStore(tmp_path)
    seen = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    raw = b"observation_date,BAMLH0A0HYM2\n2026-10-06,3.2\n"
    put(store, "hy_oas", raw, seen)
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test",
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span><span class="series-meta-value-frequency">Daily</span>',
        seen,
    )
    protocol = json.load(open("research/sentinel/6b-2g-contracts/protocol.json"))
    report, _ = replay(store, protocol, seen)
    assert report["decision_session"] == "2026-10-06"
    assert report["snapshot_status"] == "UNAVAILABLE"
    assert report["cutoff_eligible_points"] == 0
    assert report["completed_monitored_decisions"] == 0


def test_metadata_unit_rejects_unrelated_percent_text(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    seen = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    raw = b"observation_date,BAMLH0A0HYM2\n2026-10-06,3.2\n"
    record = put(store, "hy_oas", raw, seen)
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test",
        b'BAMLH0A0HYM2 Percent Daily <span class="series-meta-value-units">Index</span><span class="series-meta-value-frequency">Daily</span>',
        seen,
    )
    with pytest.raises(ValueError, match="metadata mismatch"):
        binding_for("hy_oas", record, raw, store, calendar)


def test_metadata_cannot_leak_into_earlier_replay(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    seen = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    raw = b"observation_date,BAMLH0A0HYM2\n2026-10-06,3.2\n"
    record = put(store, "hy_oas", raw, seen)
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test",
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span><span class="series-meta-value-frequency">Daily</span>',
        datetime(2026, 10, 8, 18, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="metadata not captured"):
        binding_for("hy_oas", record, raw, store, calendar, as_of=seen)


def test_later_revision_preserves_original_cutoff_snapshot(tmp_path):
    store = CaptureStore(tmp_path)
    first = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
    old = b"observation_date,BAMLH0A0HYM2\n2026-10-05,3.2\n"
    put(store, "hy_oas", old, first)
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test",
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span><span class="series-meta-value-frequency">Daily</span>',
        first,
    )
    protocol = json.load(open("research/sentinel/6b-2g-contracts/protocol.json"))
    cutoff = datetime(2026, 10, 6, 22, tzinfo=timezone.utc)
    original, projection = replay(store, protocol, cutoff)
    assert projection["market_now"]["credit"][0]["state"]["value"]["amount"] == 320
    put(
        store,
        "hy_oas",
        b"observation_date,BAMLH0A0HYM2\n2026-10-05,3.8\n",
        datetime(2026, 10, 7, 18, tzinfo=timezone.utc),
    )
    revised, _ = replay(
        store, protocol, datetime(2026, 10, 7, 18, tzinfo=timezone.utc), "2026-10-06"
    )
    assert revised["snapshot_id"] == original["snapshot_id"]
    assert revised["causal_prefix_replay"] == "PASS"


def test_partial_etf_row_stays_excluded_from_capture(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    seen = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    days = ["2026-10-06", "2026-10-07"]
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "SPY",
                        "currency": "USD",
                        "instrumentType": "ETF",
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [
                        int(calendar.get(d).opens_at.timestamp()) for d in days
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100, 101],
                                "high": [102, 103],
                                "low": [99, 100],
                                "close": [101, 102],
                                "volume": [1000, 2000],
                            }
                        ],
                        "adjclose": [{"adjclose": [100.5, 101.5]}],
                    },
                }
            ],
        }
    }
    raw = json.dumps(payload).encode()
    record = store.put("spy", "yahoo-chart-v8", "https://example.test", raw, seen)
    binding, _ = binding_for("spy", record, raw, store, calendar)
    points, counts = normalize_capture("spy", binding, record, raw, calendar)
    assert len(points) == 1 and counts["incomplete_observations_excluded"] == 1
    assert points[0].value == 100.5
    assert normalize_capture("spy", binding, record, raw, calendar)[0] == points
