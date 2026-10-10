"""Descriptive reports retain actual capture time and never claim past knowledge."""

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path

import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.observation_runner import (
    build_report,
    descriptive_calendar,
    main,
)


@pytest.fixture(scope="module")
def calendar():
    return load_xnys_calendar(date(2026, 9, 1), date(2026, 10, 31))


@pytest.fixture(scope="module")
def protocol():
    return json.loads(
        Path("research/sentinel/6b-2g-contracts/protocol.json").read_text()
    )


def yahoo_payload(calendar, prices, feed="spy"):
    sessions = calendar.history("2026-10-09", len(prices))
    return json.dumps(
        {
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
                                    "open": prices,
                                    "high": [p + 1 for p in prices],
                                    "low": [p - 1 for p in prices],
                                    "close": prices,
                                    "volume": [1000] * len(prices),
                                }
                            ],
                            "adjclose": [{"adjclose": prices}],
                        },
                    }
                ],
            }
        }
    ).encode()


def put_yahoo(store, calendar, prices, seen, feed="spy"):
    return store.put(
        feed,
        "yahoo-chart-v8",
        "https://example.test/" + feed,
        yahoo_payload(calendar, prices, feed),
        seen,
    )


def test_descriptive_cutoff_preserves_frozen_calendar_and_actual_time(calendar):
    frozen_version = calendar.calendar_version
    frozen_cutoff = calendar.get("2026-10-09").decision_cutoff
    actual_asof = datetime(2026, 10, 9, 20, 15, tzinfo=timezone.utc)

    descriptive = descriptive_calendar(calendar, actual_asof)

    assert descriptive.get("2026-10-09").decision_cutoff == actual_asof
    assert descriptive.get("2026-10-08").decision_cutoff == actual_asof
    assert descriptive.calendar_version != frozen_version
    assert all(s.closes_at <= actual_asof for s in descriptive.sessions)
    assert calendar.calendar_version == frozen_version
    assert calendar.get("2026-10-09").decision_cutoff == frozen_cutoff
    assert frozen_cutoff == datetime(2026, 10, 9, 22, tzinfo=timezone.utc)


def test_descriptive_watermark_rejects_naive_time(calendar):
    with pytest.raises(ValueError):
        descriptive_calendar(calendar, datetime(2026, 10, 10, 12))


def sensor(market_now, dimension, sensor_id):
    return next(
        e["state"] for e in market_now[dimension] if e["sensor_id"] == sensor_id
    )


def test_latest_capture_reconstructs_comparison_without_backdating(
    tmp_path, calendar, protocol
):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    prices = [100 + i + i * i / 100 for i in range(22)]
    capture = put_yahoo(store, calendar, prices, actual_seen)

    report = build_report(store, protocol, actual_seen, calendar)
    current = sensor(report["market_now"], "broad_equity", "spy_return_20")
    previous = sensor(report["previous_market_now"], "broad_equity", "spy_return_20")

    assert report["session_id"] == "2026-10-09"
    assert report["previous_session_id"] == "2026-10-08"
    assert current["value"]["amount"] == pytest.approx(math.log(prices[21] / prices[1]))
    assert previous["value"]["amount"] == pytest.approx(
        math.log(prices[20] / prices[0])
    )
    assert report["market_now"]["as_of"] == actual_seen.isoformat()
    assert report["previous_market_now"]["as_of"] == actual_seen.isoformat()
    assert report["comparison_policy"] == "SAME_CAPTURE_VINTAGE_NOT_HISTORICAL_KNOWN"
    assert report["report_kind"] == "LATEST_VINTAGE_DESCRIPTIVE_ONLY"
    assert "DESCRIPTIVE_ONLY" in current["qualifiers"]
    assert "DESCRIPTIVE_ONLY" in previous["qualifiers"]
    assert report["source_results"][0]["first_seen_at"] == actual_seen.isoformat()
    assert (
        store.get(capture["capture_id"])[0]["first_seen_at"] == actual_seen.isoformat()
    )
    assert report["original_calendar_version"] == calendar.calendar_version
    assert report["production_enabled"] is False
    assert report["admission_status"] == "BLOCKED_DATA"
    assert report["market_now"]["conditional_forecasts"] == []
    assert report["market_now"]["reference_values"] == []


def test_future_capture_cannot_change_same_asof_report(tmp_path, calendar, protocol):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    prices = [100 + i + i * i / 100 for i in range(22)]
    put_yahoo(store, calendar, prices, actual_seen)
    original = build_report(store, protocol, actual_seen, calendar)
    revised_prices = prices[:-1] + [prices[-1] * 1.1]
    future = put_yahoo(
        store, calendar, revised_prices, actual_seen + timedelta(hours=1)
    )

    replayed = build_report(store, protocol, actual_seen, calendar)

    assert replayed["market_now"] == original["market_now"]
    assert replayed["previous_market_now"] == original["previous_market_now"]
    assert replayed["input_capture_ids"] == original["input_capture_ids"]
    assert future["capture_id"] not in replayed["input_capture_ids"]
    assert len(replayed["source_results"]) == len(original["source_results"])


def test_http_failure_stays_null_without_fabricated_market_value(
    tmp_path, calendar, protocol
):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    prices = [100 + i + i * i / 100 for i in range(22)]
    put_yahoo(store, calendar, prices, actual_seen)
    failed = store.put(
        "rsp",
        "yahoo-chart-v8",
        "https://example.test/rsp",
        b"upstream unavailable",
        actual_seen,
        status=503,
        error="HTTP_ERROR",
    )

    report = build_report(store, protocol, actual_seen, calendar)
    rsp = sensor(report["market_now"], "broad_equity", "rsp_return_20")
    participation = sensor(report["market_now"], "participation", "rsp_spy_relative_20")
    source = next(
        r for r in report["source_results"] if r["capture_id"] == failed["capture_id"]
    )

    assert rsp["value"] is None
    assert participation["value"] is None
    assert rsp["data_status"] != "AVAILABLE"
    assert source["http_status"] == 503
    assert source["status"] == "SOURCE_ERROR"


def successful_equity_captures(store, calendar, seen):
    prices = [100 + i + i * i / 100 for i in range(22)]
    captures = {
        feed: put_yahoo(store, calendar, [p * scale for p in prices], seen, feed)
        for feed, scale in (("spy", 1), ("rsp", 0.9), ("qqq", 1.2))
    }
    return prices, captures


def assert_spy_and_dependencies_unavailable(report):
    for market in (report["market_now"], report["previous_market_now"]):
        for dimension, sensor_id in (
            ("broad_equity", "spy_return_20"),
            ("volatility", "spy_rv_20"),
            ("volatility", "spy_rv_5_over_20"),
            ("participation", "rsp_spy_relative_20"),
            ("leadership", "qqq_spy_relative_20"),
        ):
            state = sensor(market, dimension, sensor_id)
            assert state["value"] is None
            assert state["data_status"] != "AVAILABLE"
        assert sensor(market, "broad_equity", "rsp_return_20")["value"] is not None


def test_later_failed_fetch_blocks_previous_success_for_both_compared_dates(
    tmp_path, calendar, protocol
):
    store = CaptureStore(tmp_path)
    first = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    failed_at = first + timedelta(hours=1)
    _, captures = successful_equity_captures(store, calendar, first)
    original = build_report(store, protocol, first, calendar)
    failed = store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test/spy",
        b"unavailable",
        failed_at,
        status=503,
        error="HTTP_ERROR",
    )

    degraded = build_report(store, protocol, failed_at, calendar)

    assert_spy_and_dependencies_unavailable(degraded)
    assert degraded["freshness_status"] == "DEGRADED_LATEST_FETCH_FAILED"
    assert degraded["latest_fetch_failed_feeds"] == ["spy"]
    assert (
        degraded["market_now"]["coverage"]["active_required"]["available"]
        < original["market_now"]["coverage"]["active_required"]["available"]
    )
    assert (
        degraded["previous_market_now"]["coverage"]["active_required"]["available"]
        < original["previous_market_now"]["coverage"]["active_required"]["available"]
    )
    latest = next(
        r for r in degraded["source_results"] if r["capture_id"] == failed["capture_id"]
    )
    previous = next(
        r
        for r in degraded["source_results"]
        if r["capture_id"] == captures["spy"]["capture_id"]
    )
    assert latest["is_latest_attempt"] is True
    assert latest["latest_attempt_at"] == failed_at.isoformat()
    assert latest["latest_attempt_capture_id"] == failed["capture_id"]
    assert latest["last_success_capture_id"] == captures["spy"]["capture_id"]
    assert latest["last_success_at"] == first.isoformat()
    assert latest["used_for_report"] is False
    assert previous["used_for_report"] is False
    assert previous["is_latest_attempt"] is False
    assert (
        store.get(captures["spy"]["capture_id"])[0]["first_seen_at"]
        == first.isoformat()
    )
    assert len(store.records()) == 4


def test_future_failed_fetch_cannot_degrade_earlier_asof(tmp_path, calendar, protocol):
    store = CaptureStore(tmp_path)
    first = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    successful_equity_captures(store, calendar, first)
    original = build_report(store, protocol, first, calendar)
    future = store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test/spy",
        b"unavailable",
        first + timedelta(hours=1),
        status=503,
        error="HTTP_ERROR",
    )

    replayed = build_report(store, protocol, first, calendar)

    assert replayed["freshness_status"] == "LATEST_ATTEMPTS_SUCCEEDED"
    assert replayed["latest_fetch_failed_feeds"] == []
    assert replayed["market_now"] == original["market_now"]
    assert replayed["previous_market_now"] == original["previous_market_now"]
    assert replayed["source_results"] == original["source_results"]
    assert future["capture_id"] not in replayed["input_capture_ids"]


def test_successful_recovery_restores_measurements_after_failed_attempt(
    tmp_path, calendar, protocol
):
    store = CaptureStore(tmp_path)
    first = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    prices, _ = successful_equity_captures(store, calendar, first)
    store.put(
        "spy",
        "yahoo-chart-v8",
        "https://example.test/spy",
        b"unavailable",
        first + timedelta(hours=1),
        status=503,
        error="HTTP_ERROR",
    )
    recovery_at = first + timedelta(hours=2)
    changed = prices[:-1] + [prices[-1] * 1.01]
    recovered = put_yahoo(store, calendar, changed, recovery_at)

    report = build_report(store, protocol, recovery_at, calendar)

    assert report["freshness_status"] == "LATEST_ATTEMPTS_SUCCEEDED"
    assert report["latest_fetch_failed_feeds"] == []
    current = sensor(report["market_now"], "broad_equity", "spy_return_20")
    prior = sensor(report["previous_market_now"], "broad_equity", "spy_return_20")
    assert current["value"]["amount"] == pytest.approx(
        math.log(changed[21] / changed[1])
    )
    assert prior["value"]["amount"] == pytest.approx(math.log(changed[20] / changed[0]))
    assert current["captured_at"] == recovery_at.isoformat()
    assert sensor(report["market_now"], "volatility", "spy_rv_20")["value"] is not None
    assert (
        sensor(report["market_now"], "participation", "rsp_spy_relative_20")["value"]
        is not None
    )
    latest = next(
        r
        for r in report["source_results"]
        if r["capture_id"] == recovered["capture_id"]
    )
    assert latest["is_latest_attempt"] is True
    assert latest["used_for_report"] is True


@pytest.mark.parametrize("invalid_kind", ["schema", "completed_value", "empty_history"])
def test_latest_http_200_invalid_payload_blocks_cached_measurements(
    tmp_path, calendar, protocol, invalid_kind
):
    store = CaptureStore(tmp_path)
    first = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    prices, _ = successful_equity_captures(store, calendar, first)
    if invalid_kind == "schema":
        raw = b'{"chart":{"error":null,"result":[]}}'
    elif invalid_kind == "completed_value":
        payload = json.loads(yahoo_payload(calendar, prices))
        payload["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][-1] = -1
        raw = json.dumps(payload).encode()
    else:
        payload = json.loads(yahoo_payload(calendar, []))
        raw = json.dumps(payload).encode()
    failed_at = first + timedelta(hours=1)
    invalid = store.put(
        "spy", "yahoo-chart-v8", "https://example.test/spy", raw, failed_at
    )

    report = build_report(store, protocol, failed_at, calendar)

    assert_spy_and_dependencies_unavailable(report)
    assert report["freshness_status"] == "DEGRADED_LATEST_FETCH_FAILED"
    assert report["latest_fetch_failed_feeds"] == ["spy"]
    latest = next(
        r for r in report["source_results"] if r["capture_id"] == invalid["capture_id"]
    )
    assert latest["http_status"] == 200
    assert latest["status"] == "SOURCE_ERROR"
    assert latest["used_for_report"] is False


def test_future_metadata_cannot_validate_current_series(tmp_path, calendar, protocol):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    store.put(
        "hy_oas",
        "fred-public-csv",
        "https://example.test/hy_oas",
        b"observation_date,BAMLH0A0HYM2\n2026-10-08,3.2\n",
        actual_seen,
    )
    future = store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test/hy_oas_metadata",
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span>'
        b'<span class="series-meta-value-frequency">Daily</span>',
        actual_seen + timedelta(hours=1),
    )

    report = build_report(store, protocol, actual_seen, calendar)

    assert sensor(report["market_now"], "credit", "hy_oas_level")["value"] is None
    assert future["capture_id"] not in report["input_capture_ids"]
    source = next(r for r in report["source_results"] if r["feed_id"] == "hy_oas")
    assert source["status"] == "SOURCE_ERROR"


def test_full_day_observation_label_is_not_next_midnight_date(
    tmp_path, calendar, protocol
):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    store.put(
        "hy_oas",
        "fred-public-csv",
        "https://example.test/hy_oas",
        b"observation_date,BAMLH0A0HYM2\n2026-10-08,3.2\n",
        actual_seen,
    )
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test/hy_oas_metadata",
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span>'
        b'<span class="series-meta-value-frequency">Daily</span>',
        actual_seen,
    )

    report = build_report(store, protocol, actual_seen, calendar)
    credit = sensor(report["market_now"], "credit", "hy_oas_level")

    assert report["session_id"] == "2026-10-09"
    assert credit["value"]["amount"] == 320
    assert credit["state_as_of"] == "2026-10-09T04:00:00+00:00"
    assert credit["observation_label"] == "2026-10-08"
    assert credit["captured_at"] == actual_seen.isoformat()


@pytest.mark.parametrize("metadata_failure", ["http", "units"])
def test_latest_failed_metadata_cannot_reuse_earlier_valid_units(
    tmp_path, calendar, protocol, metadata_failure
):
    store = CaptureStore(tmp_path)
    first = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    raw_metadata = (
        b'BAMLH0A0HYM2 <span class="series-meta-value-units">Percent</span>'
        b'<span class="series-meta-value-frequency">Daily</span>'
    )
    initial_capture = store.put(
        "hy_oas",
        "fred-public-csv",
        "https://example.test/hy_oas",
        b"observation_date,BAMLH0A0HYM2\n2026-10-08,3.2\n",
        first,
    )
    store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test/metadata",
        raw_metadata,
        first,
    )
    original = build_report(store, protocol, first, calendar)
    assert (
        sensor(original["market_now"], "credit", "hy_oas_level")["value"]["amount"]
        == 320
    )
    failed_at = first + timedelta(hours=1)
    failed = store.put(
        "hy_oas_metadata",
        "fred-series-metadata",
        "https://example.test/metadata",
        (
            b"unavailable"
            if metadata_failure == "http"
            else raw_metadata.replace(b"Percent", b"Dollars")
        ),
        failed_at,
        status=503 if metadata_failure == "http" else 200,
        error="HTTP_ERROR" if metadata_failure == "http" else None,
    )

    report = build_report(store, protocol, failed_at, calendar)

    assert report["freshness_status"] == "DEGRADED_LATEST_FETCH_FAILED"
    assert report["latest_fetch_failed_feeds"] == ["hy_oas"]
    for market in (report["market_now"], report["previous_market_now"]):
        assert sensor(market, "credit", "hy_oas_level")["value"] is None
    source = next(r for r in report["source_results"] if r["feed_id"] == "hy_oas")
    assert source["status"] == "SOURCE_ERROR"
    assert source["latest_metadata_attempt_at"] == failed_at.isoformat()
    assert source["latest_metadata_attempt_capture_id"] == failed["capture_id"]
    assert source["last_success_capture_id"] == initial_capture["capture_id"]
    assert source["last_success_at"] == first.isoformat()


def test_intraday_bar_is_excluded_from_closed_session_report(
    tmp_path, calendar, protocol
):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 9, 18, tzinfo=timezone.utc)
    prices = [100 + i + i * i / 100 for i in range(22)]
    put_yahoo(store, calendar, prices, actual_seen)

    report = build_report(store, protocol, actual_seen, calendar)

    assert report["session_id"] == "2026-10-08"
    current = sensor(report["market_now"], "broad_equity", "spy_return_20")
    assert current["value"]["amount"] == pytest.approx(math.log(prices[20] / prices[0]))
    assert (
        report["source_results"][0]["normalization"]["incomplete_observations_excluded"]
        == 1
    )


@pytest.mark.parametrize("pilot_marker", ["configuration.json", "profiles"])
def test_pilot_store_is_refused_without_rewriting_its_records(
    tmp_path, calendar, protocol, pilot_marker
):
    store = CaptureStore(tmp_path)
    actual_seen = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    prices = [100 + i + i * i / 100 for i in range(22)]
    capture = put_yahoo(store, calendar, prices, actual_seen)
    marker = tmp_path / pilot_marker
    if pilot_marker == "profiles":
        marker.mkdir()
    else:
        marker.write_text('{"frozen": true}')
    before = store.get(capture["capture_id"])

    with pytest.raises(ValueError, match="separate non-pilot store"):
        build_report(store, protocol, actual_seen, calendar)

    assert store.get(capture["capture_id"]) == before
    assert list((tmp_path / "bindings").iterdir()) == []
    if pilot_marker == "configuration.json":
        assert marker.read_text() == '{"frozen": true}'


@pytest.mark.parametrize("pilot_marker", ["configuration.json", "profiles"])
def test_cli_refuses_pilot_before_fetching_or_creating_store(
    tmp_path, monkeypatch, pilot_marker
):
    root = tmp_path / "pilot"
    root.mkdir()
    if pilot_marker == "profiles":
        (root / pilot_marker).mkdir()
    else:
        (root / pilot_marker).write_text('{"frozen": true}')
    # Even a misplaced observation marker must not allow writes to a pilot store.
    (root / "observation-profile.json").write_text(
        '{"schema_version":"sentinel-observation-store-v1",'
        '"purpose":"LATEST_VINTAGE_DESCRIPTIVE_ONLY"}'
    )
    before = sorted(p.relative_to(root) for p in root.rglob("*"))

    def forbidden_fetch(*args, **kwargs):
        pytest.fail("pilot guard must run before any source capture")

    monkeypatch.setattr(
        "dx27.adapters.sentinel.observation_runner.capture_sources", forbidden_fetch
    )
    monkeypatch.setattr(
        "sys.argv",
        ["observation_runner", "--store", str(root), "--output", str(tmp_path / "out")],
    )
    with pytest.raises(ValueError, match="separate non-pilot store"):
        main()

    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
    assert not (tmp_path / "out").exists()
