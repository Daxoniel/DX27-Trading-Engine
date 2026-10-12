"""Forecast prices keep one sealed vintage and never conceal later failures."""

from datetime import date, datetime, timedelta, timezone
import json

import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.forecast_inputs import (
    FORECAST_FEEDS,
    extract_price_context,
)
from dx27.adapters.sentinel.recorded_sources import binding_for


ORIGIN = "2026-10-09"
AS_OF = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def calendar():
    return load_xnys_calendar(date(2025, 1, 1), date(2027, 1, 31))


def payload(calendar, prices, feed="spy", *, sessions=None):
    sessions = sessions or calendar.history(ORIGIN, len(prices))
    return {
        "chart": {
            "error": None,
            "result": [{
                "meta": {
                    "symbol": feed.upper(),
                    "currency": "USD",
                    "instrumentType": "ETF",
                    "exchangeTimezoneName": "America/New_York",
                },
                "timestamp": [int(session.opens_at.timestamp()) for session in sessions],
                "indicators": {
                    "quote": [{
                        "open": prices,
                        "high": [price + 1 for price in prices],
                        "low": [price - 1 for price in prices],
                        "close": prices,
                        "volume": [1000] * len(prices),
                    }],
                    "adjclose": [{"adjclose": prices}],
                },
            }],
        },
    }


def put(store, calendar, prices, *, seen=AS_OF, feed="spy", data=None):
    return store.put(
        feed,
        "yahoo-chart-v8",
        "https://example.test/" + feed,
        json.dumps(payload(calendar, prices, feed) if data is None else data).encode(),
        seen,
    )


def report(*records, as_of=AS_OF, origin=ORIGIN):
    return {
        "as_of": as_of.isoformat(),
        "session_id": origin,
        "source_results": [{
            **record,
            "is_latest_attempt": True,
            "used_for_report": True,
            "status": "NORMALIZED_DESCRIPTIVE",
        } for record in records],
    }


def test_default_253_prices_reuses_adjustment_basis_and_exact_session_chain(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    prices = [100 + i / 10 for i in range(253)]
    records = [put(store, calendar, prices, feed=feed) for feed in FORECAST_FEEDS]
    context = extract_price_context(store, report(*records), calendar)

    assert context["context_sessions"] == 253
    assert context["session_ids"] == [s.session_id for s in calendar.history(ORIGIN, 253)]
    assert context["prices"] == {feed: prices for feed in FORECAST_FEEDS}
    assert context["unavailable"] == {}
    for feed, record in zip(FORECAST_FEEDS, records):
        assert context["sources"][feed] == {
            key: record[key] for key in ("capture_id", "payload_sha256", "first_seen_at")
        }
    # No returns or measurements masquerade as the captured prices.
    assert context["prices"]["spy"][-1] == prices[-1]


def test_uses_captured_adjusted_closes_instead_of_unadjusted_quote_prices(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    data = payload(calendar, [100, 101, 102])
    data["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"] = [200, 205, 210]
    latest = put(store, calendar, [], data=data)

    context = extract_price_context(store, report(latest), calendar, 3)

    assert context["prices"]["spy"] == [200, 205, 210]


def test_future_capture_does_not_change_existing_watermark(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    original = put(store, calendar, [100, 101, 102])
    original_report = report(original)
    before = extract_price_context(store, original_report, calendar, 3)
    put(store, calendar, [500, 501, 502], seen=AS_OF + timedelta(hours=1))

    assert extract_price_context(store, original_report, calendar, 3) == before


def test_latest_failure_blocks_even_a_report_that_claims_old_success_is_current(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    earlier = put(store, calendar, [100, 101, 102], seen=AS_OF - timedelta(minutes=1))
    store.put("spy", "yahoo-chart-v8", "https://example.test/spy", b"failed", AS_OF, status=503)

    context = extract_price_context(store, report(earlier), calendar, 3)

    assert "spy" not in context["prices"]
    assert "spy" not in context["sources"]
    assert context["unavailable"]["spy"] == "LATEST_FETCH_FAILED"


def test_later_success_recovers_using_only_the_new_capture(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    put(store, calendar, [100, 101, 102], seen=AS_OF - timedelta(minutes=2))
    store.put("spy", "yahoo-chart-v8", "https://example.test/spy", b"failed", AS_OF - timedelta(minutes=1), status=503)
    current = put(store, calendar, [200, 210, 220])

    context = extract_price_context(store, report(current), calendar, 3)

    assert context["prices"]["spy"] == [200, 210, 220]
    assert context["sources"]["spy"]["capture_id"] == current["capture_id"]


@pytest.mark.parametrize("change", ["stale_capture", "not_used", "not_latest", "bad_status"])
def test_report_source_must_match_real_latest_usable_capture(tmp_path, calendar, change):
    store = CaptureStore(tmp_path)
    old = put(store, calendar, [100, 101, 102], seen=AS_OF - timedelta(minutes=1))
    current = put(store, calendar, [200, 201, 202])
    observation = report(old if change == "stale_capture" else current)
    source = observation["source_results"][0]
    if change == "not_used":
        source["used_for_report"] = False
    elif change == "not_latest":
        source["is_latest_attempt"] = False
    elif change == "bad_status":
        source["status"] = "SOURCE_ERROR"

    context = extract_price_context(store, observation, calendar, 3)

    assert "spy" not in context["prices"]
    assert context["unavailable"]["spy"] == "REPORT_SOURCE_NOT_CURRENT_AND_USABLE"


def test_context_gap_does_not_pull_missing_prices_from_an_older_capture(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    sessions = calendar.history(ORIGIN, 4)
    put(store, calendar, [100, 101, 102, 103], seen=AS_OF - timedelta(minutes=1))
    incomplete = payload(calendar, [200, 202, 203], sessions=[sessions[0], sessions[2], sessions[3]])
    latest = put(store, calendar, [], data=incomplete)

    context = extract_price_context(store, report(latest), calendar, 4)

    assert "spy" not in context["prices"]
    assert context["unavailable"]["spy"] == "INCOMPLETE_CONTIGUOUS_CONTEXT"


def test_fetched_incomplete_intraday_bar_is_not_a_context_price(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    sessions = (*calendar.history(ORIGIN, 3), calendar.get("2026-10-12"))
    during_session = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    data = payload(calendar, [100, 101, 102, 999], sessions=sessions)
    # Even malformed intraday OHLC is excluded as an incomplete observation.
    data["chart"]["result"][0]["indicators"]["quote"][0]["high"][-1] = 1
    latest = put(store, calendar, [], data=data, seen=during_session)

    context = extract_price_context(store, report(latest, as_of=during_session), calendar, 3)

    assert context["prices"]["spy"] == [100, 101, 102]
    assert context["session_ids"][-1] == ORIGIN


def test_early_capture_missing_origin_close_cannot_use_the_incomplete_price(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    during_session = datetime(2026, 10, 9, 15, tzinfo=timezone.utc)
    latest = put(store, calendar, [100, 101, 102], seen=during_session)

    context = extract_price_context(store, report(latest), calendar, 3)

    assert context["unavailable"]["spy"] == "INCOMPLETE_CONTIGUOUS_CONTEXT"


@pytest.mark.parametrize("invalid", ["identity", "adjustment", "old_completed_ohlc", "duplicate", "bad_timestamp", "extreme_timestamp"])
def test_invalid_latest_provider_context_is_an_abstention_not_a_fallback(tmp_path, calendar, invalid):
    store = CaptureStore(tmp_path)
    prices = [100 + i / 10 for i in range(253)]
    put(store, calendar, prices, seen=AS_OF - timedelta(minutes=1))
    data = payload(calendar, prices)
    result = data["chart"]["result"][0]
    if invalid == "identity":
        result["meta"]["symbol"] = "QQQ"
    elif invalid == "adjustment":
        result["indicators"]["adjclose"][0]["adjclose"][-1] = float("nan")
    elif invalid == "old_completed_ohlc":
        # Earlier than the report's 64-session scope, still in model context.
        result["indicators"]["quote"][0]["high"][0] = 1
    elif invalid == "duplicate":
        result["timestamp"][0] = result["timestamp"][1]
    elif invalid == "bad_timestamp":
        result["timestamp"][0] += 60
    elif invalid == "extreme_timestamp":
        result["timestamp"][0] = 10 ** 100
    latest = put(store, calendar, [], data=data)

    context = extract_price_context(store, report(latest), calendar)

    assert "spy" not in context["prices"]
    assert context["unavailable"]["spy"].startswith("INVALID_LATEST_CONTEXT:")


@pytest.mark.parametrize("corruption", ["payload", "seal", "binding"])
def test_integrity_corruption_raises_instead_of_becoming_unavailable(tmp_path, calendar, corruption):
    store = CaptureStore(tmp_path)
    latest = put(store, calendar, [100, 101, 102])
    observation = report(latest)
    extract_price_context(store, observation, calendar, 3)
    if corruption == "payload":
        (tmp_path / "captures" / latest["capture_id"] / "payload.bin").write_bytes(b"changed")
    elif corruption == "seal":
        (tmp_path / "captures" / latest["capture_id"] / "seal.sha256").write_text("0" * 64)
    else:
        path = tmp_path / "bindings" / "spy.json"
        binding = json.loads(path.read_bytes())
        binding["sha256"] = "0" * 64
        path.write_text(json.dumps(binding))

    with pytest.raises(ValueError, match="changed"):
        extract_price_context(store, observation, calendar, 3)


def test_future_binding_validation_does_not_enter_an_earlier_report(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    earlier = put(store, calendar, [100, 101, 102])
    future = put(store, calendar, [200, 201, 202], seen=AS_OF + timedelta(hours=1))
    future_record, future_raw = store.get(future["capture_id"])
    binding_for("spy", future_record, future_raw, store, calendar)

    context = extract_price_context(store, report(earlier), calendar, 3)

    assert context["unavailable"]["spy"] == "BINDING_VALIDATION_AFTER_WATERMARK"
    assert "spy" not in context["prices"]


def test_sealed_source_identity_is_checked_independently_of_report_status(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    wrong_source = store.put(
        "spy",
        "wrong-provider",
        "https://example.test/spy",
        json.dumps(payload(calendar, [100, 101, 102])).encode(),
        AS_OF,
    )

    context = extract_price_context(store, report(wrong_source), calendar, 3)

    assert "spy" not in context["prices"]
    assert "source identity mismatch" in context["unavailable"]["spy"]


def test_short_calendar_is_reported_per_feed_without_aborting(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    short_calendar = load_xnys_calendar(date(2026, 10, 8), date(2026, 10, 31))

    context = extract_price_context(store, report(), short_calendar)

    assert context["prices"] == {}
    assert context["unavailable"] == {
        feed: "INSUFFICIENT_CALENDAR_CONTEXT" for feed in FORECAST_FEEDS
    }


@pytest.mark.parametrize("pilot_marker", ["configuration.json", "profiles"])
def test_pilot_store_is_refused(tmp_path, calendar, pilot_marker):
    store = CaptureStore(tmp_path)
    if pilot_marker == "profiles":
        (tmp_path / pilot_marker).mkdir()
    else:
        (tmp_path / pilot_marker).write_text("{}")

    with pytest.raises(ValueError, match="non-pilot"):
        extract_price_context(store, report(), calendar, 3)


@pytest.mark.parametrize("context_sessions", [True, 1, 2.5])
def test_invalid_context_configuration_is_refused(tmp_path, calendar, context_sessions):
    with pytest.raises(ValueError, match="context_sessions"):
        extract_price_context(CaptureStore(tmp_path), report(), calendar, context_sessions)


def test_naive_watermark_and_unfinished_or_stale_origin_are_refused(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    naive = report()
    naive["as_of"] = "2026-10-10T12:00:00"
    with pytest.raises(ValueError, match="aware"):
        extract_price_context(store, naive, calendar, 3)
    with pytest.raises(ValueError, match="not complete"):
        extract_price_context(store, report(origin="2026-10-12"), calendar, 3)
    with pytest.raises(ValueError, match="latest completed"):
        extract_price_context(store, report(origin="2026-10-08"), calendar, 3)


def test_watermark_outside_calendar_bounds_cannot_reuse_the_last_known_session(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    too_late = report(as_of=datetime(2028, 1, 1, tzinfo=timezone.utc))

    with pytest.raises(ValueError, match="outside calendar bounds"):
        extract_price_context(store, too_late, calendar, 3)


def test_calendar_identity_must_match_the_observation_report_when_provided(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    observation = report()
    observation["original_calendar_version"] = "different-calendar"
    with pytest.raises(ValueError, match="differs"):
        extract_price_context(store, observation, calendar, 3)
    observation["original_calendar_version"] = calendar.calendar_version
    context = extract_price_context(store, observation, calendar, 3)
    assert context["unavailable"]["spy"] == "NO_ELIGIBLE_CAPTURE"
