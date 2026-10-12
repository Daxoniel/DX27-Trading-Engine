"""Forecast presentation boundaries: terminal units, abstention and provenance."""

import math

import pytest

from dx27.adapters.sentinel.observation_report import render_html, render_markdown


def observation():
    return {
        "report_kind": "LATEST_VINTAGE_DESCRIPTIVE_ONLY",
        "generated_at": "2026-10-11T11:00:00+00:00",
        "session_id": "2026-10-09",
        "previous_session_id": None,
        "market_now": {
            "broad_equity": [
                {
                    "sensor_id": "spy_return_20",
                    "measurement_ref": "measured-spy",
                    "state": {
                        "data_status": "AVAILABLE",
                        "state_as_of": "2026-10-09T20:00:00+00:00",
                        "observation_label": "2026-10-09",
                        "value": {"amount": math.log(1.02), "unit": "log_return"},
                        "evidence_refs": ["actual-input"],
                        "qualifiers": [],
                    },
                }
            ],
            "coverage": {
                "active_required": {"available": 13, "expected": 13},
                "blocked": {"available": 0, "expected": 3},
            },
        },
        "source_results": [],
        "admission_status": "BLOCKED_DATA",
    }


def prediction(subject="SPY", target_type="ETF_CUMULATIVE_RETURN"):
    return {
        "subject": subject,
        "target_id": subject.lower() + "_forward_return_5",
        "target_type": target_type,
        "status": "AVAILABLE",
        "q10_return": -0.0175,
        "q50_return": 0.0025,
        "q90_return": 0.0415,
        "baseline": {"q10_return": -0.025, "q50_return": 0.0, "q90_return": 0.026},
    }


def forecast_report():
    report = observation()
    report["experimental_forecast"] = {
        "status": "AVAILABLE_EXPERIMENTAL",
        "model_id": "amazon/chronos-2",
        "model_revision": "pinned-model-revision",
        "origin_session": "2026-10-09",
        "target_session": "2026-10-16",
        "horizon_sessions": 5,
        "forecast_sessions": [
            "2026-10-12",
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
        ],
        "as_of": "2026-10-11T10:00:00+00:00",
        "issued_at": "2026-10-11T11:00:00+00:00",
        "calibration_status": "NOT_VALIDATED",
        "predictive_effectiveness": "NOT_TESTED",
        "reference_ids": ["REF-CHRONOS2-MODEL", "REF-CHRONOS2-PAPER"],
        "input_sources": {
            "spy": {
                "first_seen_at": "2026-10-11T10:00:00+00:00",
                "capture_id": "input-capture-ref",
                "payload_sha256": "sealed-response-digest",
            }
        },
        "predictions": [prediction()],
    }
    return report


def test_terminal_decimal_return_intervals_baseline_and_actual_dates_are_explicit():
    report = forecast_report()
    # Daily quantiles do not define the terminal cumulative interval.
    report["experimental_forecast"]["predictions"][0]["daily_quantiles"] = [0.7] * 5
    markdown, html = render_markdown(report), render_html(report)
    assert (
        "| SPY · 累计回报 | +0.25% | -1.75% 至 +4.15% | 0.00% / -2.50% 至 +2.60% |"
        in markdown
    )
    assert "<td>+0.25%</td>" in html
    for actual in (markdown, html):
        assert "未来 5 个交易日 · 模型实验" in actual
        assert "起点 2026-10-09 收盘" in actual and "目标 2026-10-16 收盘" in actual
        assert "名义覆盖 80%，尚未校准，不是已验证的 80% 把握" in actual
        assert "预测有效性尚未测试" in actual
        assert "随机游走：中位数 / 区间" in actual
        assert "pinned-model-revision" in actual
        assert "REF-CHRONOS2-PAPER" in actual
        assert "https://huggingface.co/amazon/chronos-2" in actual
        assert "2026-10-11 12:00:00 CEST" in actual
        assert "input-capture-ref" in actual and "sealed-response-digest" in actual
        assert "本页描述市场，不输出预测" not in actual
        assert "不累计每天的分位数" in actual
        assert "350.00%" not in actual


def test_relative_forecast_uses_direct_ratio_output_not_marginal_subtraction():
    report = forecast_report()
    spy, rsp, relative = (
        prediction(),
        prediction("RSP"),
        prediction("RSP/SPY", "RELATIVE_CUMULATIVE_RETURN"),
    )
    spy.update(q10_return=-0.01, q50_return=0.02, q90_return=0.05)
    rsp.update(q10_return=-0.04, q50_return=-0.01, q90_return=0.01)
    relative.update(q10_return=-0.015, q50_return=0.007, q90_return=0.025)
    report["experimental_forecast"]["predictions"] = [spy, rsp, relative]
    markdown = render_markdown(report)
    assert "| RSP/SPY · 相对表现 | +0.70% | -1.50% 至 +2.50% |" in markdown
    assert "不由两个 ETF 的边际分位数相减" in markdown


@pytest.mark.parametrize(
    "status,reason,expected",
    [
        ("UNAVAILABLE", "MODEL_NOT_INSTALLED", "模型运行依赖尚未安装"),
        ("FAILED", "MODEL_FAILED", "模型运行失败"),
    ],
)
def test_model_unavailability_preserves_observations_and_never_reuses_old_forecast(
    status, reason, expected
):
    report = forecast_report()
    report["experimental_forecast"].update(status=status, reason=reason)
    for actual in (render_markdown(report), render_html(report)):
        assert "未来 5 个交易日 · 模型实验" in actual
        assert expected in actual
        assert "+2.00%" in actual  # Independently valid observation remains.
        assert "+0.25%" not in actual  # Stale model values cannot survive a failed run.


@pytest.mark.parametrize(
    "quantiles",
    [
        {"q10_return": float("nan"), "q50_return": 0.0, "q90_return": 0.01},
        {"q10_return": -0.01, "q50_return": None, "q90_return": 0.01},
        {"q10_return": 0.04, "q50_return": 0.03, "q90_return": 0.02},
    ],
)
def test_invalid_quantiles_are_unavailable_instead_of_sorted_filled_or_hidden(
    quantiles,
):
    report = forecast_report()
    report["experimental_forecast"]["predictions"][0].update(quantiles)
    actual = render_markdown(report)
    assert "| SPY · 累计回报 | — | — |" in actual
    assert "分位数缺失、非有限数值或顺序异常" in actual


def test_missing_predictions_and_baseline_are_not_fabricated():
    report = forecast_report()
    report["experimental_forecast"]["predictions"][0].pop("baseline")
    actual = render_markdown(report)
    assert "| SPY · 累计回报 | +0.25% | -1.75% 至 +4.15% | — · 基准不可用 |" in actual
    report["experimental_forecast"]["predictions"] = None
    actual = render_html(report)
    assert "模型没有返回可展示的预测" in actual
    assert "+2.00%" in actual


def test_missing_structural_records_have_no_observed_time_and_coverage_is_not_complete_market():
    report = observation()
    report["market_now"]["participation"] = [
        {
            "sensor_id": "constituent_breadth_20",
            "measurement_ref": "missing-breadth-ref",
            "state": {
                "data_status": "UNAVAILABLE",
                "value": None,
                "evidence_refs": [],
                "state_as_of": "2026-10-09T20:00:00+00:00",
                "method_id": "blocked-method",
            },
        }
    ]
    html = render_html(report)
    assert "必要测量 13 / 13 可用；成分结构测量 0 / 3 可用" in html
    assert "<td>成分股上涨比例</td><td>—</td><td>缺少数据</td>" in html
    assert "缺失记录 · <code>missing-breadth-ref</code>" in html
    assert "窗口结束（柏林）" in html and "观测时点（柏林）" not in html
    assert "结束端点不是来源发布时间" in html


def test_forecast_evidence_is_escaped_and_does_not_export_context_prices():
    report = forecast_report()
    report["experimental_forecast"].update(
        model_revision="<script>bad()</script>",
        model_source_url="javascript:bad()",
        input_prices=[923456789.01234],
    )
    report["experimental_forecast"]["references"] = [
        {"reference_id": "<img src=x>", "url": "javascript:bad()"}
    ]
    for actual in (render_html(report), render_markdown(report)):
        assert "<script>" not in actual and "<img src=x>" not in actual
        assert "&lt;script&gt;" in actual
        assert "javascript:bad()" not in actual
        assert "923456789.01234" not in actual


def test_synthetic_forecast_section_does_not_claim_real_market_inference():
    report = forecast_report()
    report["report_kind"] = "SYNTHETIC_DEMO"
    for actual in (render_html(report), render_markdown(report)):
        assert "合成示例 · 非真实行情" in actual
        assert "合成输入演示，不代表真实市场" in actual


def test_legacy_observation_without_forecast_has_no_invented_model_output():
    report = observation()
    for actual in (render_html(report), render_markdown(report)):
        assert "未来 5 个交易日 · 模型实验" not in actual
        assert "amazon/chronos-2" not in actual
        assert "+2.00%" in actual
