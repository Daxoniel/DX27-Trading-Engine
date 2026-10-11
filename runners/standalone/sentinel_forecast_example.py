"""Offline synthetic display fixture; its stub is not a trained-model prediction."""

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.forecast_model import build_forecast, seal_forecast
from dx27.adapters.sentinel.observation_report import render_html, render_markdown
from dx27.adapters.sentinel.observation_runner import build_report
from runners.standalone.sentinel_observation_example import SEEN, _fixtures, _mark_synthetic, _put


PUBLIC_FILES = (
    "README.md", "synthetic-report.json", "synthetic-market-forecast.html",
    "synthetic-market-forecast.md", "degraded-synthetic-report.json",
    "degraded-synthetic-market-forecast.html", "degraded-synthetic-market-forecast.md",
)
ARCHIVE_NAME = "synthetic-forecast-demo.zip"


class DisplayStub:
    """Deterministic presentation numbers only; never used by the live runner."""

    def predict_many(self, contexts):
        return [np.array([
            [[-0.02 - 0.002 * k, 0.001 * k, 0.02 + 0.002 * k] for _ in range(5)]
            for k in range(len(context))
        ]) for context in contexts]


def synthetic_attachment(store, report, calendar, seen):
    forecast = build_forecast(store, report, DisplayStub(), calendar, issued_at=seen)
    forecast.update(
        model_id="SYNTHETIC_DISPLAY_STUB_NOT_CHRONOS2", model_revision="synthetic-fixture-v1",
        model_source_url=None, model_package_version="not-applicable",
        model_license="SYNTHETIC_FIXTURE_ONLY", inference_seconds=0.0,
        inference_config={"device": "offline_display_stub", "training": False},
        report_kind="SYNTHETIC_DEMO", real_market_observations=0,
    )
    for key in ("forecast_id", "model_weight_sha256_expected", "model_weight_sha256"):
        forecast.pop(key, None)
    return seal_forecast(forecast)


def generate(output_directory):
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research/sentinel/6b-2g-contracts/protocol.json").read_text())
    calendar = load_xnys_calendar(date(2025, 1, 1), date(2026, 10, 31))
    with TemporaryDirectory(prefix="dx27-forecast-synthetic-") as temporary:
        store = CaptureStore(Path(temporary))
        _fixtures(store, calendar.history("2026-10-09", 253))
        healthy = build_report(store, protocol, SEEN, calendar)
        healthy["experimental_forecast"] = synthetic_attachment(store, healthy, calendar, SEEN)
        _mark_synthetic(healthy, SEEN)
        seen = SEEN + timedelta(minutes=1)
        _put(store, "spy", "yahoo-chart-v8", b"SYNTHETIC 503", seen, status=503, error="HTTP_ERROR")
        degraded = build_report(store, protocol, seen, calendar)
        degraded["experimental_forecast"] = synthetic_attachment(store, degraded, calendar, seen)
        _mark_synthetic(degraded, seen)
    for prefix, report in (("", healthy), ("degraded-", degraded)):
        (output / (prefix + "synthetic-report.json")).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        for suffix, render in (("html", render_html), ("md", render_markdown)):
            (output / (prefix + "synthetic-market-forecast." + suffix)).write_text(render(report), encoding="utf-8")
    (output / "README.md").write_text(
        "# 预测区展示样例\n\n所有行情由离线公式生成；预测数字来自明确标注的展示 stub，"
        "不是 Chronos-2 推理结果，也不证明任何真实预测能力。\n\n"
        "打开 synthetic-market-forecast.html；degraded-synthetic-market-forecast.html "
        "展示 SPY 最新采集失败后的部分弃权。没有原始 capture/payload 或真实市场数据。\n\n"
        "本次真实 Chronos-2 的 CPU 执行与真实行情报告保留在私有本地；"
        "本包仅验收版面、单位、边界和失效表达。\n", encoding="utf-8"
    )
    with ZipFile(output / ARCHIVE_NAME, "x", compression=ZIP_DEFLATED) as archive:
        for name in PUBLIC_FILES:
            archive.writestr(ZipInfo(name, date_time=(2026, 10, 10, 12, 0, 0)), (output / name).read_bytes(), compress_type=ZIP_DEFLATED)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    print(generate(args.output_directory) / ARCHIVE_NAME)


if __name__ == "__main__":
    main()
