"""Fixed, local Chronos-2 inference; experimental forecasts are not production gates."""

from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import hashlib
import math
from pathlib import Path
from statistics import NormalDist
import time

import numpy as np

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.forecast_inputs import extract_price_context
from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.session_calendar import utc


MODEL_ID = "amazon/chronos-2"
MODEL_REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"
PACKAGE_VERSION = "2.3.2"
MODEL_WEIGHT_SHA256 = "ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42"
CONTEXT_SESSIONS = 253
HORIZON = 5
QUANTILES = (0.1, 0.5, 0.9)
TARGETS = (
    ("spy_forward_return_5", "SPY", ("spy",)),
    ("rsp_forward_return_5", "RSP", ("rsp",)),
    ("qqq_forward_return_5", "QQQ", ("qqq",)),
    ("iwm_forward_return_5", "IWM", ("iwm",)),
    ("rsp_spy_forward_relative_5", "RSP/SPY", ("rsp", "spy")),
    ("qqq_spy_forward_relative_5", "QQQ/SPY", ("qqq", "spy")),
    ("iwm_spy_forward_relative_5", "IWM/SPY", ("iwm", "spy")),
)
REFERENCES = (
    "REF-CHRONOS2-MODEL", "REF-CHRONOS2-PAPER", "REF-TSFM-FINANCIAL-RETURNS-2026",
    "REF-CHRONOS-MULTIVARIATE-FINANCE-2026",
)


class ChronosBackend:
    """One pinned checkpoint, CPU float32, no training or cross-origin learning."""

    def __init__(self, cache_directory=Path("work/forecast-model-cache")):
        self.cache_directory = Path(cache_directory)
        self.pipeline = None
        self.weight_sha256 = None

    def predict_many(self, contexts):
        import torch
        from chronos import Chronos2Pipeline
        from huggingface_hub import hf_hub_download

        if version("chronos-forecasting") != PACKAGE_VERSION:
            raise ValueError("unsupported chronos-forecasting version")
        if self.pipeline is None:
            torch.set_num_threads(min(8, torch.get_num_threads()))
            weights = hf_hub_download(
                MODEL_ID, "model.safetensors", revision=MODEL_REVISION,
                cache_dir=str(self.cache_directory),
            )
            digest = hashlib.sha256()
            with open(weights, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != MODEL_WEIGHT_SHA256:
                raise ValueError("checkpoint weight checksum mismatch")
            self.weight_sha256 = digest.hexdigest()
            config = hf_hub_download(
                MODEL_ID, "config.json", revision=MODEL_REVISION,
                cache_dir=str(self.cache_directory),
            )
            self.pipeline = Chronos2Pipeline.from_pretrained(
                str(Path(config).parent), device_map="cpu",
                dtype=torch.float32, trust_remote_code=False, local_files_only=True,
            )
        with torch.inference_mode():
            quantiles, _ = self.pipeline.predict_quantiles(
                [{"target": np.asarray(c, dtype=np.float32)} for c in contexts],
                prediction_length=HORIZON, quantile_levels=list(QUANTILES),
                context_length=CONTEXT_SESSIONS, batch_size=64,
                cross_learning=False,
            )
        return [q.detach().cpu().numpy().astype(float) for q in quantiles]


def target_contexts(price_context):
    """Log price and log relative-price levels, each anchored at its own last value."""
    prices = price_context["prices"]
    available, matrices = [], []
    for target_id, subject, feeds in TARGETS:
        if any(feed not in prices for feed in feeds):
            continue
        level = np.log(np.asarray(prices[feeds[0]], dtype=float))
        if len(feeds) == 2:
            level = level - np.log(np.asarray(prices[feeds[1]], dtype=float))
        if len(level) < CONTEXT_SESSIONS or not np.isfinite(level).all():
            raise ValueError("invalid model context")
        level = level[-CONTEXT_SESSIONS:]
        matrices.append(level - level[-1])
        available.append((target_id, subject, feeds))
    return available, np.asarray(matrices, dtype=float)


def random_walk_baseline(log_level):
    """Zero drift, sample historical volatility, Gaussian five-session endpoint."""
    sigma = float(np.std(np.diff(log_level), ddof=1)) * math.sqrt(HORIZON)
    return {
        "model_id": "ZERO_DRIFT_GAUSSIAN_RANDOM_WALK",
        "q10_return": math.expm1(NormalDist().inv_cdf(0.1) * sigma),
        "q50_return": 0.0,
        "q90_return": math.expm1(NormalDist().inv_cdf(0.9) * sigma),
        "calibration_status": "NOT_VALIDATED",
    }


def endpoint_quantiles(values):
    """Transform terminal log-level quantiles; never sum daily marginal quantiles."""
    q = np.asarray(values, dtype=float)
    if q.shape != (HORIZON, len(QUANTILES)) or not np.isfinite(q).all():
        raise ValueError("invalid quantile shape or nonfinite forecast")
    if np.any(np.diff(q, axis=1) < 0):
        raise ValueError("crossed quantiles")
    transformed = [math.expm1(float(x)) for x in q[-1]]
    if not all(math.isfinite(v) for v in transformed):
        raise ValueError("nonfinite return forecast")
    return dict(zip(("q10_return", "q50_return", "q90_return"), transformed))


def forecast_metadata(report, calendar):
    future = [s for s in calendar.sessions if s.session_id > report["session_id"]][:HORIZON]
    return {
        "schema_version": "sentinel-experimental-forecast-v1",
        "task_id": "6B-2K-A", "status": "UNAVAILABLE",
        "as_of": report["as_of"], "origin_session": report["session_id"],
        "target_session": future[-1].session_id if len(future) == HORIZON else None,
        "forecast_sessions": [s.session_id for s in future], "horizon_sessions": HORIZON,
        "forecast_calendar_version": calendar.calendar_version,
        "context_sessions": CONTEXT_SESSIONS,
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "model_package_version": PACKAGE_VERSION, "model_license": "Apache-2.0",
        "model_weight_sha256_expected": MODEL_WEIGHT_SHA256,
        "model_source_url": "https://huggingface.co/amazon/chronos-2",
        "reference_ids": list(REFERENCES),
        "inference_config": {"device": "cpu", "dtype": "float32", "cross_learning": False,
                             "quantile_levels": list(QUANTILES), "training": False},
        "interval_kind": "NOMINAL_80_PERCENT_UNCALIBRATED",
        "calibration_status": "NOT_VALIDATED", "predictive_effectiveness": "NOT_TESTED",
        "production_enabled": False, "admission_status": "BLOCKED_DATA",
        "historical_availability": "NOT_CERTIFIED",
        "training_data_overlap": "NOT_AUDITED",
        "relative_target_policy": "DIRECT_LOG_RATIO_NOT_SUBTRACTED_MARGINAL_QUANTILES",
        "predictions": [],
    }


def seal_forecast(forecast):
    forecast["forecast_id"] = stable_content_hash(forecast)
    return forecast


def build_forecast(store, report, backend=None, calendar=None, *, issued_at=None):
    """Attach prospective experimental inference using only the report's capture prefix."""
    calendar = calendar or load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    forecast = forecast_metadata(report, calendar)
    now = utc(issued_at or datetime.now(timezone.utc))
    forecast["issued_at"] = now.isoformat()
    if len(forecast["forecast_sessions"]) != HORIZON:
        forecast["reason"] = "预测日历不足五个交易日"
        return seal_forecast(forecast)
    next_close = calendar.get(forecast["forecast_sessions"][0]).closes_at
    if utc(datetime.fromisoformat(report["as_of"])) > now or next_close <= now:
        forecast["reason"] = "观察截止时间或交易日已过期，不能补装成提前预测"
        return seal_forecast(forecast)
    context = extract_price_context(store, report, calendar, CONTEXT_SESSIONS)
    forecast["input_sources"] = context["sources"]
    forecast["input_context_digest"] = stable_content_hash(context)
    targets, matrix = target_contexts(context)
    predictions = {}
    for target_id, subject, feeds in TARGETS:
        absent = [feed for feed in feeds if feed not in context["prices"]]
        predictions[target_id] = {
            "target_id": target_id, "subject": subject,
            "target_type": "ETF_CUMULATIVE_RETURN" if len(feeds) == 1 else "RELATIVE_CUMULATIVE_RETURN",
            "status": "UNAVAILABLE", "reason": "; ".join(
                f"{feed.upper()}: {context['unavailable'].get(feed, '历史不足')}" for feed in absent
            ) if absent else "模型尚未执行",
        }
    if not targets:
        forecast["reason"] = "没有满足连续历史要求的股票输入"
        forecast["predictions"] = list(predictions.values())
        return seal_forecast(forecast)
    for index, (target_id, _, _) in enumerate(targets):
        try:
            predictions[target_id]["baseline"] = random_walk_baseline(matrix[index])
        except (ValueError, OverflowError):
            predictions[target_id]["baseline"] = {
                "status": "UNAVAILABLE", "reason": "基准计算超出数值范围"
            }
    start = time.perf_counter()
    try:
        engine = backend or ChronosBackend()
        outputs = engine.predict_many([matrix])
        if getattr(engine, "weight_sha256", None):
            forecast["model_weight_sha256"] = engine.weight_sha256
        if len(outputs) != 1 or np.asarray(outputs[0]).shape != (len(targets), HORIZON, 3):
            raise ValueError("invalid backend output shape")
        for index, (target_id, _, _) in enumerate(targets):
            entry = predictions[target_id]
            try:
                entry.update(endpoint_quantiles(outputs[0][index]), status="AVAILABLE")
                entry.pop("reason", None)
            except (ValueError, OverflowError):
                entry["reason"] = "模型返回无效或交叉的分位区间"
    except (ImportError, PackageNotFoundError):
        forecast["reason"] = "预测依赖尚未安装；请安装项目的 forecast 扩展"
    except Exception as exc:
        # Provider/model failures must not destroy the separately valid observations.
        forecast["reason"] = "模型加载或推理失败，观察数据仍可查看"
        forecast["error_type"] = type(exc).__name__
    if "reason" in forecast:
        for entry in predictions.values():
            if entry.get("reason") == "模型尚未执行":
                entry["reason"] = forecast["reason"]
    forecast["inference_seconds"] = round(time.perf_counter() - start, 3)
    finished = utc(issued_at or datetime.now(timezone.utc))
    forecast["issued_at"] = finished.isoformat()
    if next_close <= finished:
        forecast["reason"] = "推理完成前下一交易日已收盘，预测作废，请重新采集"
        for entry in predictions.values():
            entry.update(status="UNAVAILABLE", reason=forecast["reason"])
            for key in ("q10_return", "q50_return", "q90_return"):
                entry.pop(key, None)
    forecast["predictions"] = list(predictions.values())
    count = sum(p["status"] == "AVAILABLE" for p in forecast["predictions"])
    forecast["status"] = "AVAILABLE_EXPERIMENTAL" if count == len(TARGETS) else "PARTIAL" if count else "UNAVAILABLE"
    return seal_forecast(forecast)
