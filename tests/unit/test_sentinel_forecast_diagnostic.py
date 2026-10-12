"""Independent rolling-origin outcomes and loss checks with an offline backend."""

from copy import deepcopy
from datetime import date
import json
import math
from statistics import NormalDist

import numpy as np
import pytest

from dx27.adapters.calendars.xnys import load_xnys_calendar
import dx27.adapters.sentinel.forecast_diagnostic as diagnostic_module


TARGET_FEEDS = {
    "spy_forward_return_5": ("spy",),
    "rsp_forward_return_5": ("rsp",),
    "qqq_forward_return_5": ("qqq",),
    "iwm_forward_return_5": ("iwm",),
    "rsp_spy_forward_relative_5": ("rsp", "spy"),
    "qqq_spy_forward_relative_5": ("qqq", "spy"),
    "iwm_spy_forward_relative_5": ("iwm", "spy"),
}
TERMINAL_LOG_QUANTILES = (-0.04, 0.01, 0.06)


@pytest.fixture(scope="module")
def calendar():
    return load_xnys_calendar(date(2023, 1, 1), date(2027, 12, 31))


@pytest.fixture
def history(calendar):
    # Offline synthetic prices; no captured market values or vendor series.
    session_ids = [session.session_id for session in calendar.history("2026-10-09", 373)]
    prices = {}
    for k, feed in enumerate(("spy", "rsp", "qqq", "iwm")):
        prices[feed] = [
            (100 + 20 * k) * math.exp(
                (0.0002 + 0.00013 * k) * i
                + 0.006 * math.sin(i * (0.17 + k * 0.02))
            )
            for i in range(373)
        ]
    return {
        "origin_session": "2026-10-09",
        "context_sessions": 373,
        "session_ids": session_ids,
        "prices": prices,
        "sources": {feed: {"capture_id": "synthetic-" + feed} for feed in prices},
        "unavailable": {},
    }


class RecordingBackend:
    def __init__(self, invalid=()):
        self.calls = []
        self.invalid = set(invalid)

    def predict_many(self, contexts):
        self.calls.append([np.array(context, copy=True) for context in contexts])
        outputs = []
        for origin, context in enumerate(contexts):
            # Each day has distinct marginal levels. Only the day-five level
            # is the endpoint distribution, regardless of earlier marginals.
            output = np.array([
                [[value + (day - 4) * 0.07 for value in TERMINAL_LOG_QUANTILES]
                 for day in range(5)]
                for _ in context
            ])
            for target in range(len(context)):
                if (origin, target) in self.invalid:
                    output[target, -1, 0] = float("nan")
            outputs.append(output)
        return outputs


def run_diagnostic(monkeypatch, calendar, history, backend):
    calls = []
    store = object()
    report = {"as_of": "2026-10-10T12:00:00+00:00", "session_id": "2026-10-09"}

    def extract(received_store, received_report, received_calendar, context_sessions):
        calls.append((received_store, received_report, received_calendar, context_sessions))
        return deepcopy(history)

    monkeypatch.setattr(diagnostic_module, "extract_price_context", extract)
    result = diagnostic_module.diagnostic(store, report, backend, calendar)
    assert calls == [(store, report, calendar, 373)]
    return result


def raw_return(prices, feeds, start, end):
    first_growth = prices[feeds[0]][end] / prices[feeds[0]][start]
    if len(feeds) == 1:
        return first_growth - 1
    return first_growth / (prices[feeds[1]][end] / prices[feeds[1]][start]) - 1


def independent_pinball(actual, predictions):
    losses = []
    for probability, predicted in zip((0.1, 0.5, 0.9), predictions):
        difference = actual - predicted
        losses.append(
            probability * difference if difference >= 0 else (probability - 1) * difference
        )
    return sum(losses) / 3


def independent_baseline(prices, feeds, origin):
    first = origin - 252
    increments = []
    for day in range(first + 1, origin + 1):
        increment = math.log(prices[feeds[0]][day] / prices[feeds[0]][day - 1])
        if len(feeds) == 2:
            increment -= math.log(prices[feeds[1]][day] / prices[feeds[1]][day - 1])
        increments.append(increment)
    mean = sum(increments) / len(increments)
    sample_variance = sum((value - mean) ** 2 for value in increments) / (len(increments) - 1)
    scale = math.sqrt(5 * sample_variance)
    return tuple(math.exp(NormalDist().inv_cdf(probability) * scale) - 1 for probability in (0.1, 0.5, 0.9))


def test_fixed_24_nonoverlapping_five_session_windows_keep_all_seven_targets(monkeypatch, calendar, history):
    backend = RecordingBackend()
    result = run_diagnostic(monkeypatch, calendar, history, backend)

    assert result["planned_origins"] == 24
    assert result["horizon_sessions"] == 5
    assert result["context_sessions"] == 253
    assert len(result["results"]) == 24 * 7
    assert {row["target_id"] for row in result["by_target"]} == set(TARGET_FEEDS)
    for target, feeds in TARGET_FEEDS.items():
        rows = [row for row in result["results"] if row["target_id"] == target]
        windows = []
        for i, row in enumerate(rows):
            origin = 252 + i * 5
            endpoint = origin + 5
            assert row["origin_session"] == history["session_ids"][origin]
            assert row["target_session"] == history["session_ids"][endpoint]
            assert row["actual_return"] == pytest.approx(raw_return(history["prices"], feeds, origin, endpoint), abs=1e-14)
            windows.append(set(history["session_ids"][origin + 1:endpoint + 1]))
        assert sum(len(window) for window in windows) == 120
        assert len(set.union(*windows)) == 120


def test_model_receives_exactly_253_prices_as_each_origins_own_prefix(monkeypatch, calendar, history):
    backend = RecordingBackend()
    run_diagnostic(monkeypatch, calendar, history, backend)

    assert len(backend.calls) == 1
    assert len(backend.calls[0]) == 24
    for i, matrix in enumerate(backend.calls[0]):
        origin = 252 + 5 * i
        assert matrix.shape == (7, 253)
        for k, feeds in enumerate(TARGET_FEEDS.values()):
            expected = []
            for day in range(origin - 252, origin + 1):
                level = math.log(history["prices"][feeds[0]][day])
                anchor = math.log(history["prices"][feeds[0]][origin])
                if len(feeds) == 2:
                    level -= math.log(history["prices"][feeds[1]][day])
                    anchor -= math.log(history["prices"][feeds[1]][origin])
                expected.append(level - anchor)
            assert matrix[k] == pytest.approx(expected, abs=1e-14)
            assert matrix[k, -1] == 0


def test_perturbing_later_price_only_changes_legally_later_contexts(monkeypatch, calendar, history):
    before_backend = RecordingBackend()
    before = run_diagnostic(monkeypatch, calendar, history, before_backend)
    changed = deepcopy(history)
    change_at = 277
    changed["prices"]["spy"][change_at] *= 1.2
    after_backend = RecordingBackend()
    after = run_diagnostic(monkeypatch, calendar, changed, after_backend)

    for i in range(24):
        original_matrix = before_backend.calls[0][i]
        changed_matrix = after_backend.calls[0][i]
        if 252 + 5 * i < change_at:
            np.testing.assert_array_equal(changed_matrix, original_matrix)
        else:
            assert not np.array_equal(changed_matrix, original_matrix)
        # Independent RSP/QQQ/IWM price contexts cannot react to a SPY edit.
        np.testing.assert_array_equal(changed_matrix[1:4], original_matrix[1:4])
    old_rows = [row for row in before["results"] if row["target_session"] < history["session_ids"][change_at]]
    new_rows = [row for row in after["results"] if row["target_session"] < history["session_ids"][change_at]]
    assert new_rows == old_rows
    affected_outcome = next(row for row in after["results"] if row["target_id"] == "spy_forward_return_5" and row["target_session"] == history["session_ids"][change_at])
    corresponding = next(row for row in before["results"] if row["target_id"] == affected_outcome["target_id"] and row["origin_session"] == affected_outcome["origin_session"])
    assert affected_outcome["actual_return"] != corresponding["actual_return"]


def test_endpoint_return_and_pinball_losses_match_independent_scalar_oracles(monkeypatch, calendar, history):
    result = run_diagnostic(monkeypatch, calendar, history, RecordingBackend())
    expected_model = tuple(math.exp(level) - 1 for level in TERMINAL_LOG_QUANTILES)
    keys = ("q10_return", "q50_return", "q90_return")

    for row in result["results"]:
        origin = history["session_ids"].index(row["origin_session"])
        feeds = TARGET_FEEDS[row["target_id"]]
        actual = raw_return(history["prices"], feeds, origin, origin + 5)
        expected_baseline = independent_baseline(history["prices"], feeds, origin)
        assert tuple(row["model"][key] for key in keys) == pytest.approx(expected_model)
        assert tuple(row["baseline"][key] for key in keys) == pytest.approx(expected_baseline, abs=1e-14)
        assert row["model_pinball"] == pytest.approx(independent_pinball(actual, expected_model), abs=1e-14)
        assert row["baseline_pinball"] == pytest.approx(independent_pinball(actual, expected_baseline), abs=1e-14)
        assert row["model_median_absolute_error"] == pytest.approx(abs(actual - expected_model[1]))
        assert row["baseline_median_absolute_error"] == pytest.approx(abs(actual))
        assert row["model_interval_hit"] is (expected_model[0] <= actual <= expected_model[2])
        assert row["baseline_interval_hit"] is (expected_baseline[0] <= actual <= expected_baseline[2])
    summary = next(row for row in result["by_target"] if row["target_id"] == "spy_forward_return_5")
    independent_losses = [
        independent_pinball(raw_return(history["prices"], ("spy",), 252 + 5 * i, 257 + 5 * i), expected_model)
        for i in range(24)
    ]
    assert summary["mean_model_pinball"] == pytest.approx(sum(independent_losses) / 24)


def test_invalid_forecasts_keep_frozen_24_origin_denominator(monkeypatch, calendar, history):
    result = run_diagnostic(monkeypatch, calendar, history, RecordingBackend(invalid={(0, 0), (7, 0)}))
    summary = next(row for row in result["by_target"] if row["target_id"] == "spy_forward_return_5")
    rows = [row for row in result["results"] if row["target_id"] == "spy_forward_return_5"]

    assert len(rows) == 24
    assert summary["planned_origins"] == 24
    assert summary["paired_valid"] == 22
    assert summary["failed_forecasts"] == 2
    for i in (0, 7):
        assert rows[i]["status"] == "UNAVAILABLE"
        assert rows[i]["reason"] == "INVALID_MODEL_QUANTILES"
        assert "actual_return" in rows[i]
        assert "model_pinball" not in rows[i]
    assert sum(row["planned_origins"] for row in result["by_target"]) == 168


def test_all_failed_target_still_has_24_forecasts_and_no_fabricated_mean(monkeypatch, calendar, history):
    result = run_diagnostic(monkeypatch, calendar, history, RecordingBackend(invalid={(i, 0) for i in range(24)}))
    summary = next(row for row in result["by_target"] if row["target_id"] == "spy_forward_return_5")

    assert summary["paired_valid"] == 0
    assert summary["planned_origins"] == summary["failed_forecasts"] == 24
    assert not any(key.startswith("mean_") for key in summary)


def test_missing_spy_keeps_all_seven_targets_and_marks_four_dependent_denominators(monkeypatch, calendar, history):
    del history["prices"]["spy"]
    del history["sources"]["spy"]
    history["unavailable"]["spy"] = "LATEST_FETCH_FAILED"
    result = run_diagnostic(monkeypatch, calendar, history, RecordingBackend())

    assert result["planned_targets"] == 7
    assert set(result["expected_target_ids"]) == set(TARGET_FEEDS)
    summaries = {row["target_id"]: row for row in result["by_target"]}
    assert set(summaries) == set(TARGET_FEEDS)
    assert sum(row["planned_origins"] for row in summaries.values()) == 168
    for target, feeds in TARGET_FEEDS.items():
        summary = summaries[target]
        if "spy" in feeds:
            assert summary["paired_valid"] == 0
            assert summary["failed_forecasts"] == summary["planned_origins"] == 24
            assert summary["reason"] == "INPUT_SOURCE_UNAVAILABLE"
            assert not any(key.startswith("mean_") for key in summary)
        else:
            assert summary["paired_valid"] == summary["planned_origins"] == 24
            assert summary["failed_forecasts"] == 0


def test_diagnostic_never_claims_admitted_oos_calibration_or_production(monkeypatch, calendar, history):
    result = run_diagnostic(monkeypatch, calendar, history, RecordingBackend())

    assert result["status"] == "COMPLETED_DIAGNOSTIC_ONLY"
    assert result["evaluation_kind"] == "RETROSPECTIVE_LATEST_VINTAGE_NOT_ADMITTED_OOS"
    assert result["future_input_policy"] == "PREFIX_ONLY_CROSS_ORIGIN_LEARNING_DISABLED"
    assert result["prospective_observations"] == 0
    assert result["training_overlap"] == "NOT_AUDITED"
    assert result["historical_availability"] == "NOT_CERTIFIED"
    assert result["calibration_status"] == "NOT_VALIDATED"
    assert result["admission_status"] == "BLOCKED_DATA"
    assert result["predictive_effectiveness"] == "NOT_TESTED"
    assert result["production_enabled"] is False
    assert "PASS" not in result.values()


def test_absent_price_context_keeps_protocol_size_and_does_not_run_model(monkeypatch, calendar, history):
    history["prices"] = {}
    history["sources"] = {}
    history["unavailable"] = {feed: "INCOMPLETE_CONTIGUOUS_CONTEXT" for feed in ("spy", "rsp", "qqq", "iwm")}
    backend = RecordingBackend()
    result = run_diagnostic(monkeypatch, calendar, history, backend)

    assert result["status"] == "UNAVAILABLE"
    assert result["planned_origins"] == 24
    assert result["results"] == []
    assert len(result["by_target"]) == 7
    assert {row["target_id"] for row in result["by_target"]} == set(TARGET_FEEDS)
    assert sum(row["planned_origins"] for row in result["by_target"]) == 168
    assert all(row["paired_valid"] == 0 and row["failed_forecasts"] == 24 for row in result["by_target"])
    assert backend.calls == []
    assert result["predictive_effectiveness"] == "NOT_TESTED"
    assert result["admission_status"] == "BLOCKED_DATA"


@pytest.mark.parametrize("failure", ["exception", "missing_origin", "wrong_horizon", "wrong_quantiles"])
def test_whole_backend_failure_is_a_serializable_168_forecast_failure_artifact(monkeypatch, calendar, history, failure):
    class FailedBackend:
        def predict_many(self, contexts):
            if failure == "exception":
                raise RuntimeError("offline synthetic inference failure")
            if failure == "missing_origin":
                return []
            shape = (7, 4, 3) if failure == "wrong_horizon" else (7, 5, 2)
            return [np.zeros(shape) for _ in range(24)]

    result = run_diagnostic(monkeypatch, calendar, history, FailedBackend())

    assert result["model_failure"] == ("RuntimeError" if failure == "exception" else "ValueError")
    assert len(result["results"]) == 168
    assert all(row["status"] == "UNAVAILABLE" for row in result["results"])
    assert sum(row["planned_origins"] for row in result["by_target"]) == 168
    for row in result["by_target"]:
        assert row["planned_origins"] == row["failed_forecasts"] == 24
        assert row["paired_valid"] == 0
        assert not any(key.startswith("mean_") for key in row)
    assert result["predictive_effectiveness"] == "NOT_TESTED"
    assert result["production_enabled"] is False
    json.dumps(result, allow_nan=False)


def test_diagnostic_records_pinned_model_config_weights_and_input_digest(monkeypatch, calendar, history):
    backend = RecordingBackend()
    backend.weight_sha256 = "a" * 64
    result = run_diagnostic(monkeypatch, calendar, history, backend)

    assert result["model_id"] == "amazon/chronos-2"
    assert result["model_revision"] == "29ec3766d36d6f73f0696f85560a422f50e8498c"
    assert result["model_package_version"] == "2.3.2"
    assert result["model_weight_sha256"] == "a" * 64
    assert result["inference_config"] == {
        "device": "cpu", "dtype": "float32", "cross_learning": False,
        "quantile_levels": [0.1, 0.5, 0.9], "training": False,
    }
    assert len(result["input_context_digest"]) == 64
    assert set(result["input_context_digest"]) <= set("0123456789abcdef")
    same_inputs = run_diagnostic(monkeypatch, calendar, history, RecordingBackend())
    assert same_inputs["input_context_digest"] == result["input_context_digest"]
    history["prices"]["spy"][-1] *= 1.001
    changed = run_diagnostic(monkeypatch, calendar, history, RecordingBackend())
    assert changed["input_context_digest"] != result["input_context_digest"]


def test_nonfinite_actual_return_is_unavailable_and_remains_serializable(monkeypatch, calendar, history):
    # Both captured prices are positive and finite, but their growth ratio is
    # too large for a float. It must not become a valid infinite outcome.
    history["prices"]["spy"][252] = 1e-200
    history["prices"]["spy"][257] = 1e200
    with np.errstate(over="ignore", invalid="ignore"):
        result = run_diagnostic(monkeypatch, calendar, history, RecordingBackend())

    first_spy = next(row for row in result["results"] if row["target_id"] == "spy_forward_return_5")
    assert first_spy["status"] == "UNAVAILABLE"
    assert first_spy["reason"] == "INVALID_ACTUAL_RETURN"
    assert first_spy["actual_return"] is None
    assert "model_pinball" not in first_spy
    summary = next(row for row in result["by_target"] if row["target_id"] == "spy_forward_return_5")
    assert summary["planned_origins"] == 24
    assert summary["paired_valid"] + summary["failed_forecasts"] == 24
    json.dumps(result, allow_nan=False)
