"""Create reproducible, offline synthetic report examples; accept no market data."""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.sentinel.capture_store import CaptureStore
from dx27.adapters.sentinel.observation_report import render_html, render_markdown
from dx27.adapters.sentinel.observation_runner import build_report
from dx27.adapters.sentinel.recorded_sources import ETF_IDS, FRED_IDS


SEEN = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
PUBLIC_FILES = (
    "README.md",
    "synthetic-report.json",
    "synthetic-market-observation.html",
    "synthetic-market-observation.md",
    "degraded-synthetic-report.json",
    "degraded-synthetic-market-observation.html",
    "degraded-synthetic-market-observation.md",
)
ARCHIVE_NAME = "synthetic-observation-demo.zip"


def _put(store, feed, source, raw, seen=SEEN, **kwargs):
    return store.put(
        feed, source, "https://synthetic.example.invalid/" + feed, raw, seen, **kwargs
    )


def _fixtures(store, sessions):
    drifts = (0.001, -0.0002, 0.0022, -0.001, 0.003, -0.002, 0.0015)
    for index, feed in enumerate(ETF_IDS):
        prices = [
            100 * math.exp(drifts[index % len(drifts)] * i + 0.003 * math.sin(i))
            for i in range(len(sessions))
        ]
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
            }
        }
        _put(store, feed, "yahoo-chart-v8", json.dumps(payload).encode())
    csv = "DATE,OPEN,HIGH,LOW,CLOSE\n" + "".join(
        f"{date.fromisoformat(s.session_id):%m/%d/%Y},18,19,17,{18 + i / 10}\n"
        for i, s in enumerate(sessions)
    )
    _put(store, "vix", "cboe-daily-csv", csv.encode())
    for feed, base in (
        ("hy_oas", 3.2),
        ("ust_2y", 4.1),
        ("ust_10y", 4.6),
        ("sofr", 4.8),
        ("effr", 4.75),
    ):
        series = FRED_IDS[feed]
        csv = (
            "observation_date,"
            + series
            + "\n"
            + "".join(
                f"{s.session_id},{base + i / 1000}\n"
                for i, s in enumerate(sessions[:-1])
            )
        )
        _put(store, feed, "fred-public-csv", csv.encode())
        metadata = (
            f"<title>SYNTHETIC {series}</title>"
            '<span class="series-meta-value-units">Percent</span>'
            '<span class="series-meta-value-frequency">Daily</span>'
        )
        _put(store, feed + "_metadata", "fred-series-metadata", metadata.encode())


def _mark_synthetic(report, as_of):
    report.update(
        report_kind="SYNTHETIC_DEMO",
        generated_at=as_of.isoformat(),
        data_role="SYNTHETIC_FIXTURE_ONLY",
        real_market_observations=0,
    )

    def mark(value):
        if isinstance(value, dict):
            if "source_id" in value:
                value["source_id"] = "SYNTHETIC_FIXTURE"
            for child in value.values():
                mark(child)
        elif isinstance(value, list):
            for child in value:
                mark(child)

    mark(report)
    return report


def generate(output_directory):
    """Generate from internal formulas only; persist no captures in the output."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "research/sentinel/6b-2g-contracts/protocol.json"
        ).read_text()
    )
    calendar = load_xnys_calendar(date(2026, 6, 1), date(2026, 10, 31))
    with TemporaryDirectory(prefix="dx27-synthetic-observation-") as temporary:
        store = CaptureStore(Path(temporary))
        _fixtures(store, calendar.history("2026-10-09", 22))
        healthy = _mark_synthetic(build_report(store, protocol, SEEN, calendar), SEEN)
        failure_seen = SEEN + timedelta(minutes=1)
        _put(
            store,
            "spy",
            "yahoo-chart-v8",
            b"SYNTHETIC HTTP 503",
            failure_seen,
            status=503,
            error="HTTP_ERROR",
        )
        degraded = _mark_synthetic(
            build_report(store, protocol, failure_seen, calendar), failure_seen
        )
    for prefix, report in (("", healthy), ("degraded-", degraded)):
        (output / (prefix + "synthetic-report.json")).write_text(
            json.dumps(
                report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            )
            + "\n",
            encoding="utf-8",
        )
        for suffix, renderer in (("html", render_html), ("md", render_markdown)):
            (output / (prefix + "synthetic-market-observation." + suffix)).write_text(
                renderer(report), encoding="utf-8"
            )
    (output / "README.md").write_text(
        "# 合成报告展示样例\n\n所有数值均由离线公式生成，不是真实市场数据。\n\n"
        "双击 synthetic-market-observation.html 查看正常样例；"
        "degraded-synthetic-market-observation.html 展示最新 SPY 采集失败。\n\n"
        "日期固定为 2026-10-09，仅用于展示。原始 payload 和 capture store 不在此包内。"
        "本样例不证明真实数据覆盖率、预测有效性或生产准入。\n\n"
        "在仓库中复现：\n\n```bash\npython -m runners.standalone.sentinel_observation_example "
        "--output-directory work/new-synthetic-demo\n```\n",
        encoding="utf-8",
    )
    with ZipFile(output / ARCHIVE_NAME, "x", compression=ZIP_DEFLATED) as archive:
        for name in PUBLIC_FILES:
            entry = ZipInfo(name, date_time=(2026, 10, 10, 12, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, (output / name).read_bytes())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    print(generate(parser.parse_args().output_directory))


if __name__ == "__main__":
    main()
