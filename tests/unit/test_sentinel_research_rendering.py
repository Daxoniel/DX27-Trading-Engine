"""Synthetic research attachments keep comparison, failure and evidence truthful."""

from copy import deepcopy

import pytest

from dx27.adapters.sentinel.observation_report import render_html, render_markdown


def research_report():
    return {
        "report_kind": "SYNTHETIC_DEMO",
        "generated_at": "2026-10-12T10:00:00+00:00",
        "session_id": "2026-10-09",
        "previous_session_id": None,
        "market_now": {},
        "source_results": [],
        "research_trends": {
            "status": "AVAILABLE",
            "change_status": "UNCHANGED",
            "headline": "盈利预期与价格表现尚未出现新的分化。",
            "brief_lines": ["可用资料仍指向行业轮动。", "Mega7 集中度仍需补充证据。"],
            "changes": [],
            "compared_to": "2026-10-11T09:00:00+00:00",
            "notices": ["NERI 为三个月修订广度均值，保留各来源原始期限。"],
            "sector_rows": [{
                "sector": "科技",
                "earnings_revision": "上修",
                "price_change": "上涨",
                "breadth": "暂无成分股数据",
                "interpretation": "盈利与价格同向",
                "period": "合成研究周 2026-10-09",
                "evidence": "REF-SYNTHETIC-YARDENI · 第 3 页 · 图 2",
            }],
            "structure_rows": [{
                "metric": "Mega7 盈利份额",
                "value": "份额上升（合成示例）",
                "change": "与上次快照一致",
                "observed_on": "2026-10-09",
                "evidence": "REF-SYNTHETIC-FACTSET · 第 5 页 · 表 1",
            }],
            "sources": [
                {
                    "name": "Yardeni",
                    "status": "AVAILABLE",
                    "publication_date": "2026-10-09",
                    "retrieved_at": "2026-10-12T09:58:00+00:00",
                    "url": "https://research.example.org/yardeni.pdf",
                    "reference_id": "REF-SYNTHETIC-YARDENI",
                    "document_id": "synthetic-yardeni-document",
                    "locator": "第 3 页 · 图 2",
                    "errors": [],
                },
                {
                    "name": "FactSet",
                    "status": "AVAILABLE",
                    "publication_date": "2026-10-09",
                    "retrieved_at": "2026-10-12T09:59:00+00:00",
                    "url": "https://research.example.org/factset.pdf",
                    "reference_id": "REF-SYNTHETIC-FACTSET",
                    "document_id": "synthetic-factset-document",
                    "reference_locator": "第 5 页 · 表 1",
                    "errors": [],
                },
            ],
        },
    }


def add_forecast(report):
    report["experimental_forecast"] = {
        "status": "AVAILABLE_EXPERIMENTAL",
        "model_id": "amazon/chronos-2",
        "origin_session": "2026-10-09",
        "target_session": "2026-10-16",
        "horizon_sessions": 5,
        "predictions": [{
            "subject": "SPY",
            "status": "AVAILABLE",
            "q10_return": -0.01,
            "q50_return": 0.02,
            "q90_return": 0.03,
        }],
    }


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_research_brief_leads_market_facts_with_saved_snapshot_comparison(render):
    actual = render(research_report())
    assert actual.index("本次趋势简报") < actual.index("一分钟观察")
    assert "未发现变化" in actual
    assert "与上次实际保存快照比较（柏林）：2026-10-11 11:00:00 CEST" in actual
    assert "市场观察的对比按本次取得的历史版本重算" in actual
    assert "基于盈利预期的趋势解读，尚未验证为预测" in actual
    assert "暂无真实成分股广度、头部权重及 Mega7 回报贡献" in actual
    assert "合成研究输入演示，不代表真实市场" in actual
    assert "80%" not in actual  # The qualitative brief adds no numeric probability.


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_first_research_snapshot_does_not_claim_unchanged_or_display_old_changes(render):
    report = research_report()
    report["research_trends"].update(
        change_status="INITIAL",
        compared_to=None,
        changes=["old-comparison-must-not-appear"],
    )
    actual = render(report)
    assert "首期无比较" in actual
    assert "未发现变化" not in actual
    assert "old-comparison-must-not-appear" not in actual
    assert "与上次实际保存快照比较（柏林）" not in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_changed_summary_uses_saved_snapshot_and_keeps_front_prose_short(render):
    report = research_report()
    report["research_trends"].update(
        change_status="CHANGED",
        changes=["科技盈利预期转为上修。", "价格与盈利方向趋同。", "可用行业增加。", "fourth-change-hidden"],
        brief_lines=["brief-one", "brief-two", "brief-three", "fourth-brief-hidden"],
    )
    actual = render(report)
    assert "发现变化" in actual
    assert actual.index("科技盈利预期转为上修。") < actual.index("一分钟观察")
    assert "2026-10-11 11:00:00 CEST" in actual
    assert "fourth-change-hidden" not in actual
    assert "fourth-brief-hidden" not in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
@pytest.mark.parametrize("compared_to", ["2026-10-11T09:00:00+00:00", None])
def test_incomparable_period_or_coverage_is_not_presented_as_trend_change(render, compared_to):
    report = research_report()
    report["research_trends"].update(
        change_status="INCOMPARABLE",
        compared_to=compared_to,
        changes=["incomparable-old-change-must-not-appear"],
    )
    actual = render(report)
    assert "口径或覆盖更新 · 暂不能比较" in actual
    assert "本次口径或覆盖不同，暂不能直接比较" in actual
    assert "发现变化" not in actual
    assert "首期无比较" not in actual
    assert "incomparable-old-change-must-not-appear" not in actual
    assert "盈利与价格同向" in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_successful_research_does_not_hide_failure_of_entire_market_collection(render):
    report = research_report()
    report["market_refresh_error"] = "<script>market_error()</script>"
    actual = render(report)
    assert "研究来源可用" in actual
    assert "行情采集失败：本次未取得市场观察" in actual
    assert "采集不完整" in actual
    assert "上次成功的数据不代替本次采集" in actual
    assert "market_error()" not in actual
    assert "本次趋势简报" in actual and "尚不能回答的部分" in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_partial_research_names_failed_source_and_keeps_current_available_context(render):
    report = research_report()
    report["research_trends"]["status"] = "PARTIAL"
    report["research_trends"]["sources"][1].update(
        status="SOURCE_ERROR", publication_date=None, errors=["synthetic-http-503"],
    )
    actual = render(report)
    assert "研究来源部分可用" in actual
    assert "本次来源缺口：FactSet" in actual
    assert "旧值不作为本次数据" in actual
    assert "盈利与价格同向" in actual
    assert "来源采集失败" in actual
    assert "synthetic-http-503" in actual
    assert "发布日期：未提供" in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_unavailable_research_never_promotes_saved_headline_rows_or_changes(render):
    report = research_report()
    attachment = report["research_trends"]
    attachment.update(status="UNAVAILABLE", change_status="CHANGED", changes=["stale-change"])
    for source in attachment["sources"]:
        source["status"] = "SOURCE_ERROR"
    actual = render(report)
    assert "本次研究来源不可用" in actual
    assert "本次无法判断趋势有无变化" in actual
    assert "上次保存的数据不代替本次采集" in actual
    assert attachment["headline"] not in actual
    assert attachment["brief_lines"][0] not in actual
    assert "盈利与价格同向" not in actual
    assert "份额上升（合成示例）" not in actual
    assert "stale-change" not in actual
    assert "一分钟观察" in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_research_evidence_escapes_external_text_and_uses_safe_source_urls(render):
    report = research_report()
    attachment = report["research_trends"]
    attachment.update(
        headline="<script>bad()</script>",
        brief_lines=["<img src=x onerror=bad()>", "[bad](javascript:attack())"],
        change_status="CHANGED",
        changes=["<svg onload=bad()>"],
    )
    attachment["sector_rows"][0]["sector"] = "<iframe src=bad>"
    attachment["sector_rows"][0]["evidence"] = "<script>sector()</script>"
    attachment["structure_rows"][0]["value"] = "<b onclick=bad()>"
    attachment["structure_rows"][0]["evidence"] = "<script>structure()</script>"
    attachment["notices"] = ["<script>notice()</script>"]
    attachment["sources"][0].update(
        name="<img src=x>",
        url="https://user:password@research.example.org/yardeni.pdf?token=secret#private",
        document_id="<script>doc()</script>",
        locator="<script>page()</script>",
        errors=["<script>error()</script>"],
    )
    attachment["sources"][1]["url"] = "javascript:url_only_payload()"
    actual = render(report)
    for tag in ("<script>", "<img src=x", "<svg onload=", "<iframe src=", "<b onclick="):
        assert tag not in actual
    assert "&lt;script&gt;" in actual
    assert "url_only_payload" not in actual
    assert "password" not in actual and "token=secret" not in actual
    if render is render_html:
        assert 'href="https://research.example.org/yardeni.pdf"' in actual
    else:
        assert r"\[bad\]\(javascript:attack\(\)\)" in actual


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_source_references_include_publication_retrieval_and_page_separately(render):
    actual = render(research_report())
    assert "<summary>研究来源、发布日期与页码</summary>" in actual
    assert "发布日期：2026-10-09" in actual
    assert "取回（柏林）：2026-10-12 11:58:00 CEST" in actual
    assert "REF-SYNTHETIC-YARDENI" in actual
    assert "synthetic-yardeni-document" in actual
    assert "第 3 页 · 图 2" in actual
    assert "第 5 页 · 表 1" in actual
    assert "行业对照" in actual and "盈利预期与市场结构" in actual
    assert "合成研究周 2026-10-09" in actual
    assert "科技：REF-SYNTHETIC-YARDENI · 第 3 页 · 图 2" in actual
    assert "Mega7 盈利份额：REF-SYNTHETIC-FACTSET · 第 5 页 · 表 1" in actual
    assert actual.index("研究来源、发布日期与页码") < actual.index("NERI 为三个月修订广度均值")


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_research_moves_forecast_to_closed_final_appendix(render):
    report = research_report()
    add_forecast(report)
    actual = render(report)
    assert actual.index("本次趋势简报") < actual.index("一分钟观察")
    assert actual.index("尚不能回答的部分") < actual.index("实验附录 · 模型预测")
    assert actual.index("实验附录 · 模型预测") < actual.index("未来 5 个交易日 · 模型实验")
    assert "+2.00%" in actual
    assert "名义覆盖 80%，尚未校准" in actual
    assert "open" not in actual.split("实验附录 · 模型预测")[0].rsplit("<details", 1)[1]


@pytest.mark.parametrize("render", [render_html, render_markdown])
def test_absent_optional_attachment_preserves_legacy_forecast_placement(render):
    report = research_report()
    report.pop("research_trends")
    add_forecast(report)
    actual = render(report)
    assert "本次趋势简报" not in actual
    assert "实验附录 · 模型预测" not in actual
    assert actual.index("未来 5 个交易日 · 模型实验") < actual.index("尚不能回答的部分")
    without_attachment = deepcopy(report)
    without_attachment["research_trends"] = None
    assert render(without_attachment) == actual
