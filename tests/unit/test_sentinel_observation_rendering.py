"""Presentation checks for truthful units, missingness and safe evidence."""

import math

from dx27.adapters.sentinel.observation_report import render_html, render_markdown


def entry(sensor_id, amount, unit="log_return", day="2026-10-09", status="AVAILABLE"):
    return {
        "sensor_id": sensor_id,
        "measurement_ref": "measurement-" + sensor_id,
        "state": {
            "data_status": status,
            "state_as_of": day + "T20:00:00+00:00",
            "observation_label": day,
            "value": (
                {"amount": amount, "unit": unit} if status == "AVAILABLE" else None
            ),
            "evidence_refs": ["point-" + sensor_id],
            "qualifiers": [],
        },
    }


def report(current, previous=None):
    return {
        "schema_version": "sentinel-observation-v1",
        "report_kind": "LATEST_VINTAGE_DESCRIPTIVE_ONLY",
        "generated_at": "2026-10-10T11:00:00+00:00",
        "session_id": "2026-10-09",
        "previous_session_id": "2026-10-08" if previous is not None else None,
        "market_now": {"broad_equity": current},
        "previous_market_now": (
            {"broad_equity": previous} if previous is not None else None
        ),
        "source_results": [],
        "admission_status": "BLOCKED_DATA",
    }


def test_log_return_is_simple_return_and_delta_is_percentage_points():
    actual = render_markdown(
        report(
            [entry("spy_return_20", math.log(1.10))],
            [entry("spy_return_20", math.log(1.08), day="2026-10-08")],
        )
    )
    assert (
        "| SPY · 标普 500 市值加权 | +10.00% | +2.00 个百分点 | 2026-10-09 |" in actual
    )
    assert "不是当天收益" in actual


def test_missing_previous_is_not_a_zero_delta_or_unchanged():
    actual = render_markdown(report([entry("vix_level", 20.0, "percent_annualized")]))
    assert "| VIX · 30 日期权隐含波动率 | 20.00% | 前次不可用，无法比较 |" in actual
    assert "没有变化" not in actual.replace("不推断为没有变化", "")
    assert "暂无前次完整观察" in actual


def test_missing_current_has_no_fabricated_measurement_or_change():
    actual = render_markdown(
        report(
            [entry("hy_oas_level", None, "basis_points", status="SOURCE_ERROR")],
            [entry("hy_oas_level", 300.0, "basis_points", day="2026-10-08")],
        )
    )
    assert "— · 来源采集失败 | 当前不可用，无法比较" in actual
    assert "300.00 bp" not in actual


def test_derived_absolute_returns_require_identical_observation_instants():
    current = [
        entry("spy_return_20", math.log(1.10)),
        entry("qqq_spy_relative_20", math.log(1.20 / 1.10)),
    ]
    aligned = render_markdown(report(current))
    assert "| QQQ · 纳斯达克 100 | +20.00% |" in aligned
    current[1]["state"]["state_as_of"] = "2026-10-09T19:00:00+00:00"
    misaligned = render_markdown(report(current))
    assert "| QQQ · 纳斯达克 100 | — · 缺少数据 |" in misaligned


def test_same_lagged_observation_is_not_claimed_to_be_stable_credit():
    actual = render_markdown(
        report(
            [entry("hy_oas_level", 300.0, "basis_points", day="2026-10-08")],
            [entry("hy_oas_level", 300.0, "basis_points", day="2026-10-08")],
        )
    )
    assert "仍为同一条观测，尚无新数据" in actual
    assert "较前次 +0.00" not in actual


def test_official_observation_label_is_not_replaced_with_exclusive_end_date():
    current = entry("hy_oas_level", 300.0, "basis_points", day="2026-10-08")
    current["state"]["state_as_of"] = "2026-10-09T04:00:00+00:00"
    actual = render_markdown(report([current]))
    assert (
        "| 美国高收益债 · 期权调整利差 | 300.00 bp | 前次不可用，无法比较 | 2026-10-08 |"
        in actual
    )


def test_all_sector_member_contexts_are_preserved_and_partial_is_visible():
    actual_report = report([])
    members = []
    for symbol, value in (("XLK", 0.03), ("XLF", -0.02), ("XLE", None)):
        row = entry(
            "sector_relative_20",
            value,
            status="AVAILABLE" if value is not None else "UNAVAILABLE",
        )
        row["state"]["value"] = (
            {"unit": "log_return", "members": [{"subject_id": symbol, "value": value}]}
            if value is not None
            else None
        )
        row["state"]["qualifiers"] = [
            "SECTOR_FEED:" + symbol.lower(),
            "PARTIAL_SECTOR_CONTEXT",
        ]
        members.append(row)
    actual_report["market_now"]["leadership"] = members
    actual = render_markdown(actual_report)
    assert "（部分可用）" in actual
    for label in ("科技 · XLK", "金融 · XLF", "能源 · XLE"):
        assert label in actual
    assert "能源 · XLE | — · 缺少数据" in actual


def test_html_escapes_evidence_and_removes_url_credentials():
    actual_report = report([])
    actual_report["source_results"] = [
        {
            "feed_id": "<script>alert(1)</script>",
            "source_id": "evil <img src=x onerror=alert(1)>",
            "url": "https://user:password@example.org/data?token=secret#private",
            "first_seen_at": "2026-10-10T11:00:00+00:00",
            "capture_id": "record-id",
            "status": "NORMALIZED_DESCRIPTIVE",
        }
    ]
    actual = render_html(actual_report)
    assert "<script>" not in actual
    assert "&lt;script&gt;" in actual
    assert 'href="https://example.org/data"' in actual
    assert "password" not in actual and "token=secret" not in actual
    assert "13:00:00 CEST" in actual
    assert "已取得并解析" in actual
    assert "不是昨天当时已知的报告" in actual


def test_fred_graph_capture_links_to_public_series_without_secret_queries():
    actual_report = report([])
    actual_report["source_results"] = [
        {
            "feed_id": "hy_oas",
            "source_id": "FRED",
            "url": "https://fred.stlouisfed.org/graph/graph.csv?id=BAMLH0A0HYM2&token=private",
            "status": "NORMALIZED_DESCRIPTIVE",
        }
    ]
    actual = render_html(actual_report)
    assert 'href="https://fred.stlouisfed.org/series/BAMLH0A0HYM2"' in actual
    assert "token=private" not in actual


def failed_report():
    actual_report = report(
        [
            entry("spy_return_20", None, status="SOURCE_ERROR"),
            entry("vix_level", 20.0, "percent_annualized"),
        ]
    )
    actual_report.update(
        freshness_status="DEGRADED_LATEST_FETCH_FAILED",
        latest_fetch_failed_feeds=["spy"],
    )
    actual_report["market_now"]["coverage"] = {
        "grade": "PARTIAL",
        "active_required": {"available": 7, "expected": 13},
    }
    previous_success = {
        "feed_id": "spy",
        "source_id": "yahoo-chart-v8",
        "first_seen_at": "2026-10-10T10:00:00+00:00",
        "http_status": 200,
        "status": "NORMALIZED_DESCRIPTIVE",
        "capture_id": "success-record",
        "is_latest_attempt": False,
        "latest_attempt_at": "2026-10-10T11:00:00+00:00",
        "latest_attempt_capture_id": "failure-record",
        "last_success_at": "2026-10-10T10:00:00+00:00",
        "last_success_capture_id": "success-record",
        "used_for_report": False,
    }
    failure = {
        **previous_success,
        "first_seen_at": "2026-10-10T11:00:00+00:00",
        "http_status": 503,
        "status": "SOURCE_ERROR",
        "reason": "unsuccessful source response",
        "capture_id": "failure-record",
        "is_latest_attempt": True,
    }
    actual_report["source_results"] = [previous_success, failure]
    return actual_report


def test_latest_failure_degrades_headline_coverage_and_first_summary_fact():
    actual_report = failed_report()
    markdown = render_markdown(actual_report)
    html = render_html(actual_report)
    assert markdown.startswith("# Sentinel · 市场观察（采集不完整）")
    assert "最新采集存在失败" in markdown
    assert "采集不完整；必要测量 7 / 13 可用" in markdown
    assert markdown.index("最新采集失败：SPY") < markdown.index("VIX 20.00%")
    assert "相关观察暂不可用；先前成功的数据不代替本次采集" in markdown
    assert "最新数据取回版本" not in markdown
    assert "<h1>市场观察 · 采集不完整</h1>" in html
    assert "最新采集失败 · 部分观察不可用" in html
    assert "最新版本 · 描述性观察" not in html
    assert "— · 来源采集失败" in markdown and "— · 来源采集失败" in html


def test_latest_source_failure_alone_still_degrades_legacy_report_header():
    actual_report = failed_report()
    actual_report.pop("freshness_status")
    actual_report.pop("latest_fetch_failed_feeds")
    assert "市场观察（采集不完整）" in render_markdown(actual_report)
    assert "最新采集失败 · 部分观察不可用" in render_html(actual_report)


def test_source_evidence_distinguishes_failed_attempt_from_last_success_and_omits_raw_arrays():
    actual_report = failed_report()
    actual_report["source_results"][-1]["raw_payload"] = {
        "adjclose": [987654321.12345],
        "timestamps": [1999999999],
    }
    for actual in (render_markdown(actual_report), render_html(actual_report)):
        assert (
            "最新尝试 · 来源采集失败（HTTP 503；unsuccessful source response；未用于本次计算）"
            in actual
        )
        assert "较早尝试 · 已取得并解析（HTTP 200；未用于本次计算）" in actual
        assert "2026-10-10 13:00:00 CEST" in actual
        assert "2026-10-10 12:00:00 CEST · success-record" in actual
        assert "上次成功（柏林）" in actual
        assert "987654321.12345" not in actual and "1999999999" not in actual
        assert "adjclose" not in actual
    assert "failure-record" in render_html(actual_report)


def test_old_failure_does_not_degrade_after_latest_success():
    actual_report = report([entry("spy_return_20", math.log(1.10))])
    actual_report["freshness_status"] = "LATEST_ATTEMPTS_SUCCEEDED"
    actual_report["latest_fetch_failed_feeds"] = []
    actual_report["source_results"] = [
        {"feed_id": "spy", "status": "SOURCE_ERROR", "is_latest_attempt": False},
        {
            "feed_id": "spy",
            "status": "NORMALIZED_DESCRIPTIVE",
            "is_latest_attempt": True,
        },
    ]
    assert "（采集不完整）" not in render_markdown(actual_report)
    assert "最新采集失败 · 部分观察不可用" not in render_html(actual_report)


def test_metadata_failure_shows_actual_later_failed_metadata_attempt():
    actual_report = failed_report()
    latest = actual_report["source_results"][-1]
    latest.update(
        feed_id="hy_oas",
        http_status=200,
        reason="FRED units metadata not captured",
        latest_metadata_http_status=503,
        latest_metadata_attempt_at="2026-10-10T12:00:00+00:00",
        latest_metadata_attempt_capture_id="metadata-failure-record",
    )
    for actual in (render_markdown(actual_report), render_html(actual_report)):
        assert "来源说明 HTTP 503" in actual
        assert "2026-10-10 14:00:00 CEST" in actual
    assert "metadata-failure-record" in render_html(actual_report)


def test_yahoo_raw_chart_endpoint_is_linked_as_public_history_page():
    actual_report = report([])
    actual_report["source_results"] = [
        {
            "feed_id": "spy",
            "source_id": "yahoo-chart-v8",
            "status": "NORMALIZED_DESCRIPTIVE",
            "url": "https://query1.finance.yahoo.com/v8/finance/chart/SPY?period1=1&period2=2&token=private",
        }
    ]
    actual = render_html(actual_report)
    assert 'href="https://finance.yahoo.com/quote/SPY/history/"' in actual
    assert "query1.finance.yahoo.com" not in actual
    assert "period1=" not in actual and "token=private" not in actual


def test_synthetic_demo_is_prominently_identified_as_not_real_market_data():
    actual_report = report([entry("spy_return_20", math.log(1.10))])
    actual_report["report_kind"] = "SYNTHETIC_DEMO"
    markdown, html = render_markdown(actual_report), render_html(actual_report)
    assert markdown.startswith("# Sentinel · 市场观察（合成示例 · 非真实行情）")
    assert "合成数据示例，非真实行情" in markdown
    assert "最新数据取回版本" not in markdown
    assert "<h1>市场观察 · 合成示例</h1>" in html
    assert "合成示例 · 非真实行情" in html
    assert "最新版本 · 描述性观察" not in html
    assert (
        "合成示例：以下数值仅演示展示方式，不代表真实行情" in markdown
        and "合成示例：以下数值仅演示展示方式，不代表真实行情" in html
    )


def test_synthetic_degradation_keeps_failure_visible_and_wraps_long_success_ids():
    actual_report = failed_report()
    actual_report["report_kind"] = "SYNTHETIC_DEMO"
    actual_report["source_results"][-1]["last_success_capture_id"] = "a" * 64
    html = render_html(actual_report)
    assert "<h1>市场观察 · 合成示例 · 采集不完整</h1>" in html
    assert "合成示例 · 非真实行情 · 采集不完整" in html
    assert '<td class="last-success">' in html
    assert ".last-success{overflow-wrap:anywhere}" in html
