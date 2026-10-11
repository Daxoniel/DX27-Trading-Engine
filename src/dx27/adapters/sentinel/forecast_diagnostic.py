"""Fixed rolling-origin sanity check, not admitted OOS or prospective evidence."""

import argparse
from datetime import date
import json
import math
from pathlib import Path

import numpy as np

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.forecast_inputs import extract_price_context
from dx27.adapters.sentinel.forecast_model import (
    CONTEXT_SESSIONS, HORIZON, QUANTILES, ChronosBackend, endpoint_quantiles,
    TARGETS, MODEL_ID, MODEL_REVISION, PACKAGE_VERSION, random_walk_baseline, target_contexts,
)
from dx27.intelligence.sentinel.identity import stable_content_hash


ORIGINS = 24


def pinball_loss(actual, quantiles):
    values = [quantiles[k] for k in ("q10_return", "q50_return", "q90_return")]
    residual = actual - np.asarray(values)
    return float(np.maximum(np.asarray(QUANTILES) * residual, (np.asarray(QUANTILES) - 1) * residual).mean())


def diagnostic(store, report, backend, calendar=None):
    """One model/configuration, 24 disjoint five-session outcome windows, no search."""
    calendar = calendar or load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    full = extract_price_context(store, report, calendar, CONTEXT_SESSIONS + ORIGINS * HORIZON)
    result = {
        "schema_version": "sentinel-forecast-diagnostic-v1",
        "evaluation_kind": "RETROSPECTIVE_LATEST_VINTAGE_NOT_ADMITTED_OOS",
        "as_of": report["as_of"], "planned_origins": ORIGINS,
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "model_package_version": PACKAGE_VERSION,
        "inference_config": {"device": "cpu", "dtype": "float32", "cross_learning": False,
                             "quantile_levels": list(QUANTILES), "training": False},
        "planned_targets": len(TARGETS), "expected_target_ids": [t[0] for t in TARGETS],
        "horizon_sessions": HORIZON, "context_sessions": CONTEXT_SESSIONS,
        "future_input_policy": "PREFIX_ONLY_CROSS_ORIGIN_LEARNING_DISABLED",
        "training_overlap": "NOT_AUDITED", "historical_availability": "NOT_CERTIFIED",
        "calibration_status": "NOT_VALIDATED", "prospective_observations": 0,
        "admission_status": "BLOCKED_DATA", "production_enabled": False,
        "predictive_effectiveness": "NOT_TESTED", "status": "UNAVAILABLE",
        "input_sources": full["sources"], "unavailable_feeds": full["unavailable"],
        "input_context_digest": stable_content_hash(full),
        "results": [], "by_target": [],
    }
    if not full["prices"]:
        result["reason"] = "INSUFFICIENT_CONTIGUOUS_HISTORY_FOR_FIXED_DIAGNOSTIC"
        result["by_target"] = [
            {"target_id": t, "subject": s, "planned_origins": ORIGINS,
             "paired_valid": 0, "failed_forecasts": ORIGINS, "reason": result["reason"]}
            for t, s, _ in TARGETS
        ]
        return result
    contexts, outcomes, target_sets = [], [], []
    for i in range(ORIGINS):
        end = CONTEXT_SESSIONS - 1 + i * HORIZON
        past = {**full, "prices": {feed: values[:end + 1] for feed, values in full["prices"].items()}}
        targets, matrix = target_contexts(past)
        contexts.append(matrix)
        target_sets.append(targets)
        actual = []
        for _, _, feeds in targets:
            values = np.log(np.asarray(full["prices"][feeds[0]], dtype=float))
            if len(feeds) == 2:
                values -= np.log(np.asarray(full["prices"][feeds[1]], dtype=float))
            try:
                outcome = math.expm1(float(values[end + HORIZON] - values[end]))
                actual.append(outcome if math.isfinite(outcome) else None)
            except OverflowError:
                actual.append(None)
        outcomes.append(actual)
    # Explicitly separate each origin's group. The backend always sets
    # cross_learning=False, so later contexts cannot inform earlier origins.
    try:
        output = backend.predict_many(contexts)
        if len(output) != ORIGINS or any(
            np.asarray(q).shape != (len(targets), HORIZON, len(QUANTILES))
            for q, targets in zip(output, target_sets)
        ):
            raise ValueError("diagnostic backend output shape mismatch")
        if getattr(backend, "weight_sha256", None):
            result["model_weight_sha256"] = backend.weight_sha256
    except Exception as exc:
        result["model_failure"] = type(exc).__name__
        output = [np.full((len(t), HORIZON, len(QUANTILES)), np.nan) for t in target_sets]
    for i, (targets, matrix, actuals, q) in enumerate(zip(target_sets, contexts, outcomes, output)):
        end = CONTEXT_SESSIONS - 1 + i * HORIZON
        for k, (target_id, subject, _) in enumerate(targets):
            row = {
                "target_id": target_id, "subject": subject,
                "origin_session": full["session_ids"][end],
                "target_session": full["session_ids"][end + HORIZON],
                "status": "UNAVAILABLE", "actual_return": actuals[k],
            }
            if actuals[k] is None:
                row["reason"] = "INVALID_ACTUAL_RETURN"
                result["results"].append(row)
                continue
            try:
                model = endpoint_quantiles(q[k])
                baseline = random_walk_baseline(matrix[k])
                actual = actuals[k]
                row.update(
                    status="PAIRED_VALID", model=model, baseline=baseline,
                    model_pinball=pinball_loss(actual, model),
                    baseline_pinball=pinball_loss(actual, baseline),
                    model_median_absolute_error=abs(actual - model["q50_return"]),
                    baseline_median_absolute_error=abs(actual),
                    model_interval_hit=model["q10_return"] <= actual <= model["q90_return"],
                    baseline_interval_hit=baseline["q10_return"] <= actual <= baseline["q90_return"],
                )
            except (ValueError, OverflowError):
                row["reason"] = "INVALID_MODEL_QUANTILES"
            result["results"].append(row)
    for target_id, subject, feeds in TARGETS:
        rows = [r for r in result["results"] if r["target_id"] == target_id]
        valid = [r for r in rows if r["status"] == "PAIRED_VALID"]
        summary = {"target_id": target_id, "subject": subject, "planned_origins": ORIGINS,
                   "paired_valid": len(valid), "failed_forecasts": ORIGINS - len(valid)}
        if any(feed not in full["prices"] for feed in feeds):
            summary["reason"] = "INPUT_SOURCE_UNAVAILABLE"
        if valid:
            for key in ("model_pinball", "baseline_pinball", "model_median_absolute_error", "baseline_median_absolute_error", "model_interval_hit", "baseline_interval_hit"):
                summary["mean_" + key] = float(np.mean([r[key] for r in valid]))
        result["by_target"].append(summary)
    result["status"] = "COMPLETED_DIAGNOSTIC_ONLY"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--forecast-cache", type=Path, default=Path("work/forecast-model-cache"))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("diagnostic output must be a new file")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = diagnostic(CaptureStore(args.store), report, ChronosBackend(args.forecast_cache))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "planned_origins": ORIGINS, "targets": len(result["by_target"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
