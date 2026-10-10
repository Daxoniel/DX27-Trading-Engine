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
