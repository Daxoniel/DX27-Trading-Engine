"""Forecast arithmetic, per-target abstention and prospective timing are explicit."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError
import json
import math
from statistics import stdev

import numpy as np
import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.forecast_model import (
    CONTEXT_SESSIONS,
    HORIZON,
    TARGETS,
    build_forecast,
    endpoint_quantiles,
)


ORIGIN = "2026-10-09"
AS_OF = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
FEEDS = ("spy", "rsp", "qqq", "iwm")


@pytest.fixture(scope="module")
def calendar():
    return load_xnys_calendar(date(2025, 1, 1), date(2027, 1, 31))


def put_prices(store, calendar, feed, prices, *, seen=AS_OF):
    sessions = calendar.history(ORIGIN, len(prices))
    raw = {
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
                                "close": prices,
                                "high": [p + 1 for p in prices],
                                "low": [p - 1 for p in prices],
                                "volume": [1000] * len(prices),
                            }
                        ],
                        "adjclose": [{"adjclose": prices}],
                    },
                }
            ],
        },
    }
    return store.put(
        feed,
        "yahoo-chart-v8",
        "https://synthetic.example.invalid/" + feed,
        json.dumps(raw).encode(),
        seen,
    )


def observation(records, *, as_of=AS_OF):
    return {
        "as_of": as_of.isoformat(),
        "session_id": ORIGIN,
        "market_now": {"synthetic_marker": "VALID_OBSERVATIONS_MUST_SURVIVE"},
        "source_results": [
            {
                **record,
                "is_latest_attempt": True,
                "used_for_report": True,
                "status": "NORMALIZED_DESCRIPTIVE",
            }
            for record in records
        ],
    }


@pytest.fixture
def inputs(tmp_path, calendar):
    store = CaptureStore(tmp_path)
    prices = {
        feed: [
            100 * math.exp((index + 1) * 0.0002 * i + 0.004 * math.sin(i / (index + 2)))
            for i in range(CONTEXT_SESSIONS)
        ]
        for index, feed in enumerate(FEEDS)
    }
    records = {feed: put_prices(store, calendar, feed, prices[feed]) for feed in FEEDS}
    return store, observation(records.values()), prices, records


class FakeBackend:
    """Record the actual model matrix and emit unmistakably distinct endpoint paths."""

    def __init__(self, *, change=None, error=None):
        self.calls = []
        self.change = change
        self.error = error
        self.output = None

    def predict_many(self, contexts):
        self.calls.append([np.asarray(c).copy() for c in contexts])
        if self.error is not None:
            raise self.error
        assert len(contexts) == 1
        count = np.asarray(contexts[0]).shape[0]
        path = np.array(
            [
                [-0.10, 0.01, 0.05],
                [-0.09, 0.02, 0.08],
                [-0.08, 0.03, 0.10],
                [-0.07, 0.04, 0.15],
                [-0.04, 0.07, 0.20],
            ]
        )
        self.output = np.stack([path + index * 0.003 for index in range(count)])
        if self.change is not None:
            self.change(self.output)
        return [self.output]


def predictions(forecast):
    return {p["target_id"]: p for p in forecast["predictions"]}


def test_terminal_endpoint_quantiles_are_not_sums_of_daily_quantiles(inputs, calendar):
    store, report, _, _ = inputs
    backend = FakeBackend()

    forecast = build_forecast(store, report, backend, calendar, issued_at=AS_OF)
    spy = predictions(forecast)["spy_forward_return_5"]

    assert forecast["status"] == "AVAILABLE_EXPERIMENTAL"
    assert spy["q10_return"] == pytest.approx(math.expm1(-0.04))
    assert spy["q50_return"] == pytest.approx(math.expm1(0.07))
    assert spy["q90_return"] == pytest.approx(math.expm1(0.20))
    assert spy["q50_return"] != pytest.approx(
        math.expm1(0.01 + 0.02 + 0.03 + 0.04 + 0.07)
    )
    assert spy["q50_return"] != pytest.approx(
        sum(math.expm1(x) for x in (0.01, 0.02, 0.03, 0.04, 0.07))
    )


def test_backend_receives_direct_anchored_log_ratio_not_subtracted_predictions(
    inputs, calendar
):
    store, report, prices, _ = inputs
    backend = FakeBackend()

    forecast = build_forecast(store, report, backend, calendar, issued_at=AS_OF)

    assert len(backend.calls) == 1 and len(backend.calls[0]) == 1
    matrix = backend.calls[0][0]
    assert matrix.shape == (7, 253)
    np.testing.assert_allclose(matrix[:, -1], np.zeros(7), atol=1e-14)
    spy_level = np.log(prices["spy"])
    rsp_level = np.log(prices["rsp"])
    np.testing.assert_allclose(matrix[0], spy_level - spy_level[-1], atol=1e-14)
    direct_ratio = np.array(
        [math.log(rsp / spy) for rsp, spy in zip(prices["rsp"], prices["spy"])]
    )
    np.testing.assert_allclose(matrix[4], direct_ratio - direct_ratio[-1], atol=1e-14)
    targets = predictions(forecast)
    relative = targets["rsp_spy_forward_relative_5"]
    assert relative["q50_return"] == pytest.approx(math.expm1(0.07 + 4 * 0.003))
    assert relative["q50_return"] != pytest.approx(
        targets["rsp_forward_return_5"]["q50_return"]
        - targets["spy_forward_return_5"]["q50_return"]
    )


def test_random_walk_baseline_uses_historical_sample_volatility_and_zero_drift(
    inputs, calendar
):
    store, report, prices, _ = inputs
    forecast = build_forecast(store, report, FakeBackend(), calendar, issued_at=AS_OF)
    targets = predictions(forecast)
    for target_id, path in (
        ("spy_forward_return_5", prices["spy"]),
        (
            "rsp_spy_forward_relative_5",
            [r / s for r, s in zip(prices["rsp"], prices["spy"])],
        ),
    ):
        historical_returns = [math.log(b / a) for a, b in zip(path, path[1:])]
        sigma_5 = stdev(historical_returns) * math.sqrt(5)
        baseline = targets[target_id]["baseline"]
        assert baseline["q50_return"] == 0
        assert baseline["q10_return"] == pytest.approx(
            math.expm1(-1.2815515655446004 * sigma_5)
        )
        assert baseline["q90_return"] == pytest.approx(
            math.expm1(1.2815515655446004 * sigma_5)
        )
        assert baseline["calibration_status"] == "NOT_VALIDATED"


@pytest.mark.parametrize(
    "invalid", ["crossed", "nan", "inf", "overflow", "wrong_shape"]
)
def test_invalid_quantiles_are_rejected_even_when_nonterminal(invalid):
    q = np.tile(np.array([-0.1, 0, 0.1]), (5, 1))
    if invalid == "crossed":
        q[0] = [0.2, 0, 0.1]
    elif invalid == "nan":
        q[0, 0] = float("nan")
    elif invalid == "inf":
        q[0, 2] = float("inf")
    elif invalid == "overflow":
        q[-1] = [1000, 1001, 1002]
    else:
        q = q[:, :2]
    with pytest.raises((ValueError, OverflowError)):
        endpoint_quantiles(q)


def test_invalid_target_output_abstains_without_erasing_other_predictions(
    inputs, calendar
):
    store, report, _, _ = inputs

    def corrupt_three_targets(output):
        output[1, 0, 0] = float("nan")
        output[4, 1] = [0.2, 0, 0.1]
        output[6, -1] = [1000, 1001, 1002]

    backend = FakeBackend(change=corrupt_three_targets)

    forecast = build_forecast(store, report, backend, calendar, issued_at=AS_OF)
    targets = predictions(forecast)

    assert forecast["status"] == "PARTIAL"
    assert sum(p["status"] == "AVAILABLE" for p in targets.values()) == 4
    for target_id in (
        "rsp_forward_return_5",
        "rsp_spy_forward_relative_5",
        "iwm_spy_forward_relative_5",
    ):
        entry = targets[target_id]
        assert entry["status"] == "UNAVAILABLE"
        assert all(
            key not in entry for key in ("q10_return", "q50_return", "q90_return")
        )
        assert "baseline" in entry
    assert targets["spy_forward_return_5"]["q50_return"] == pytest.approx(
        math.expm1(0.07)
    )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("inference failed"),
        ImportError("torch"),
        PackageNotFoundError("chronos-forecasting"),
    ],
)
def test_model_failure_keeps_observations_and_source_metadata(inputs, calendar, error):
    store, report, _, _ = inputs
    original = deepcopy(report)
    backend = FakeBackend(error=error)

    forecast = build_forecast(store, report, backend, calendar, issued_at=AS_OF)

    assert report == original
    assert forecast["status"] == "UNAVAILABLE"
    assert forecast["reason"]
    assert set(forecast["input_sources"]) == set(FEEDS)
    assert len(forecast["input_context_digest"]) == 64
    assert len(forecast["predictions"]) == 7
    assert all(p["status"] == "UNAVAILABLE" for p in forecast["predictions"])
    assert all("q50_return" not in p for p in forecast["predictions"])
    if isinstance(error, RuntimeError):
        assert forecast["error_type"] == "RuntimeError"
    else:
        assert "依赖" in forecast["reason"]


def test_backend_with_wrong_quantile_axes_is_unavailable_instead_of_misread(
    inputs, calendar
):
    store, report, _, _ = inputs

    class TransposedBackend(FakeBackend):
        def predict_many(self, contexts):
            output = super().predict_many(contexts)
            return [output[0].transpose(0, 2, 1)]

    forecast = build_forecast(
        store, report, TransposedBackend(), calendar, issued_at=AS_OF
    )

    assert forecast["status"] == "UNAVAILABLE"
    assert forecast["error_type"] == "ValueError"
    assert len(forecast["predictions"]) == 7
    assert all(
        p["status"] == "UNAVAILABLE" and "q50_return" not in p
        for p in forecast["predictions"]
    )


def test_latest_spy_failure_blocks_all_relative_targets_then_recovers(inputs, calendar):
    store, _, prices, records = inputs
    failed_at = AS_OF + timedelta(minutes=1)
    failed = store.put(
        "spy",
        "yahoo-chart-v8",
        "https://synthetic.example.invalid/spy",
        b"failed",
        failed_at,
        status=503,
    )
    failed_report = observation(
        [failed, *[records[f] for f in FEEDS if f != "spy"]], as_of=failed_at
    )
    failed_source = next(
        s for s in failed_report["source_results"] if s["feed_id"] == "spy"
    )
    failed_source.update(status="SOURCE_ERROR", used_for_report=False)
    backend = FakeBackend()

    partial = build_forecast(
        store, failed_report, backend, calendar, issued_at=failed_at
    )

    assert partial["status"] == "PARTIAL"
    assert backend.calls[0][0].shape == (3, 253)
    assert set(partial["input_sources"]) == {"rsp", "qqq", "iwm"}
    targets = predictions(partial)
    for target_id in (
        "spy_forward_return_5",
        "rsp_spy_forward_relative_5",
        "qqq_spy_forward_relative_5",
        "iwm_spy_forward_relative_5",
    ):
        assert targets[target_id]["status"] == "UNAVAILABLE"
        assert "LATEST_FETCH_FAILED" in targets[target_id]["reason"]
    assert all(
        targets[f + "_forward_return_5"]["status"] == "AVAILABLE"
        for f in ("rsp", "qqq", "iwm")
    )

    recovered_at = AS_OF + timedelta(minutes=2)
    new_prices = [p * (1 + 0.01 * i / 252) for i, p in enumerate(prices["spy"])]
    recovered = put_prices(store, calendar, "spy", new_prices, seen=recovered_at)
    recovered_report = observation(
        [recovered, *[records[f] for f in FEEDS if f != "spy"]], as_of=recovered_at
    )
    recovery_backend = FakeBackend()
    complete = build_forecast(
        store, recovered_report, recovery_backend, calendar, issued_at=recovered_at
    )

    assert complete["status"] == "AVAILABLE_EXPERIMENTAL"
    assert len(complete["predictions"]) == 7
    assert all(p["status"] == "AVAILABLE" for p in complete["predictions"])
    assert complete["input_sources"]["spy"]["capture_id"] == recovered["capture_id"]
    expected = np.log(new_prices) - math.log(new_prices[-1])
    np.testing.assert_allclose(recovery_backend.calls[0][0][0], expected, atol=1e-14)


@pytest.mark.parametrize("time_error", ["future_asof", "first_future_session_closed"])
def test_nonprospective_issue_is_unavailable_before_backend_execution(
    inputs, calendar, time_error
):
    store, report, _, _ = inputs
    backend = FakeBackend()
    if time_error == "future_asof":
        issued = AS_OF - timedelta(seconds=1)
    else:
        issued = calendar.get("2026-10-12").closes_at

    forecast = build_forecast(store, report, backend, calendar, issued_at=issued)

    assert forecast["status"] == "UNAVAILABLE"
    assert "提前预测" in forecast["reason"]
    assert backend.calls == []
    assert forecast["predictions"] == []


def test_naive_issue_time_is_rejected_before_inference(inputs, calendar):
    store, report, _, _ = inputs
    backend = FakeBackend()

    with pytest.raises(ValueError, match="timestamp"):
        build_forecast(
            store, report, backend, calendar, issued_at=datetime(2026, 10, 10, 12)
        )

    assert backend.calls == []


def test_forecast_that_finishes_after_first_target_close_is_invalidated(
    inputs, calendar, monkeypatch
):
    store, report, _, _ = inputs
    moments = iter((AS_OF, calendar.get("2026-10-12").closes_at + timedelta(seconds=1)))

    class AdvancingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(moments)

    monkeypatch.setattr(
        "dx27.adapters.sentinel.forecast_model.datetime", AdvancingClock
    )
    backend = FakeBackend()

    forecast = build_forecast(store, report, backend, calendar)

    assert len(backend.calls) == 1
    assert forecast["status"] == "UNAVAILABLE"
    assert "预测作废" in forecast["reason"]
    assert all(p["status"] == "UNAVAILABLE" for p in forecast["predictions"])
    assert all("q50_return" not in p for p in forecast["predictions"])


def test_xnys_target_dates_and_nominal_interval_never_open_validation_gates(
    inputs, calendar
):
    store, report, _, _ = inputs
    forecast = build_forecast(store, report, FakeBackend(), calendar, issued_at=AS_OF)

    # The federal holiday on October 12 is an XNYS trading session.
    assert forecast["forecast_sessions"] == [
        "2026-10-12",
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
    ]
    assert forecast["target_session"] == "2026-10-16"
    assert forecast["horizon_sessions"] == HORIZON == 5
    assert forecast["context_sessions"] == 253
    assert forecast["interval_kind"] == "NOMINAL_80_PERCENT_UNCALIBRATED"
    assert forecast["calibration_status"] == "NOT_VALIDATED"
    assert forecast["predictive_effectiveness"] == "NOT_TESTED"
    assert forecast["historical_availability"] == "NOT_CERTIFIED"
    assert forecast["training_data_overlap"] == "NOT_AUDITED"
    assert forecast["production_enabled"] is False
    assert forecast["admission_status"] == "BLOCKED_DATA"
    assert forecast["inference_config"]["training"] is False
    assert forecast["inference_config"]["cross_learning"] is False
    assert len(forecast["forecast_id"]) == 64
    assert {p["target_id"] for p in forecast["predictions"]} == {
        target[0] for target in TARGETS
    }
