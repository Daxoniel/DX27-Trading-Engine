from copy import deepcopy
from datetime import datetime, timezone

from dx27.adapters.sentinel.research_analysis import build_research_trends

NOW = datetime(2026, 2, 10, 12, tzinfo=timezone.utc)


def metric(kind="earnings_revision_pct", value=2, **changes):
    result = dict(metric_id=kind, subject_id="information_technology", value=value, unit="percent", target_period="Q1 2026", baseline_date="2025-12-31", observation_date="2026-02-09", reference_id="REF-SYNTHETIC", locator={"page": 2, "section": "Synthetic example"})
    result.update(changes)
    return result


def source(sid="factset", metrics=None, status="AVAILABLE"):
    return dict(source_id=sid, status=status, metrics=metrics or [], publication_date="2026-02-09", retrieved_at=NOW.isoformat(), source_url="https://example.com/research", document_id="synthetic", errors=[])


def compare(current, old=None):
    previous = dict(research_sources=old, generated_at="2026-02-09T12:00:00+00:00") if old is not None else None
    return build_research_trends(current, previous, NOW)


def test_first_visit_does_not_invent_unchanged_trend():
    result = compare([source(metrics=[metric()])])
    assert result["change_status"] == "INITIAL"
    assert result["compared_to"] is None


def test_same_values_in_new_document_and_retrieval_do_not_invent_changes():
    old = source(metrics=[metric()])
    new = deepcopy(old)
    new.update(document_id="new-bytes", retrieved_at="2026-02-10T12:00:00+00:00")
    result = compare([new], [old])
    assert result["change_status"] == "UNCHANGED"
    assert result["comparable_metric_count"] == 1
    assert "资料未更新不代表市场没有变化" in "".join(result["notices"])


def test_revision_sign_change_is_separate_from_amplitude_update():
    old = [source(metrics=[metric(value=2)])]
    larger = compare([source(metrics=[metric(value=3)])], old)
    lower = compare([source(metrics=[metric(value=-1)])], old)
    assert "方向延续" in larger["headline"]
    assert "方向出现变化" in lower["headline"]
    assert "科技" in lower["changes"][0]


def test_different_quarter_or_baseline_is_never_subtracted():
    old = [source(metrics=[metric(value=2)])]
    new = [source(metrics=[metric(value=-4, target_period="Q2 2026", baseline_date="2026-01-01")])]
    result = compare(new, old)
    assert result["comparable_metric_count"] == 0
    assert result["changes"] == []
    assert result["change_status"] == "INCOMPARABLE"
    assert "没有相同口径" in result["headline"]


def test_failed_latest_source_is_not_filled_from_previous_success():
    old = [source(metrics=[metric()])]
    result = compare([source(status="SOURCE_ERROR")], old)
    assert result["status"] == "UNAVAILABLE"
    assert result["sector_rows"] == []
    assert result["brief_lines"] == []


def test_partial_failure_does_not_claim_complete_unchanged_trend():
    old = [source(metrics=[metric()]), source("yardeni", [metric("sector_neri", 2)])]
    result = compare([source(metrics=[metric()]), source("yardeni", status="SOURCE_ERROR")], old)
    assert result["status"] == "PARTIAL"
    assert result["change_status"] == "UNAVAILABLE"
    assert "完整趋势无法判断" in result["headline"]


def test_price_and_revision_are_paired_only_with_matching_baseline_and_date():
    rows = compare([source(metrics=[metric(), metric("price_change_pct", 4, baseline_date="2026-01-31")])])["sector_rows"]
    assert rows[0]["price_change"] == "未取得"
    assert "伴随" not in rows[0]["interpretation"]


def test_upward_price_and_downward_earnings_are_not_called_supported():
    result = compare([source(metrics=[metric(value=-2), metric("price_change_pct", 4)])])
    assert "背离" in result["sector_rows"][0]["interpretation"]


def test_neri_cannot_fill_missing_quarterly_earnings_revision():
    result = compare([source("yardeni", [metric("sector_neri", 5, target_period="rolling_3m", baseline_date=None, observation_date=None, observation_period="2026-02")])])
    row = result["sector_rows"][0]
    assert "未取得" in row["earnings_revision"]
    assert "NERI" in row["breadth"]
    assert "当季金额" in row["earnings_revision"]


def test_future_metrics_and_nonfinite_metrics_are_excluded():
    result = compare([source(metrics=[metric(observation_date="2026-02-11"), metric("forward_pe", float("nan")), metric("price_change_pct", True)])])
    assert result["status"] == "UNAVAILABLE"
    assert result["sector_rows"] == []


def test_different_vendors_are_not_joined_into_revision_series():
    result = compare([source("yardeni", [metric(value=4)])], [source(metrics=[metric(value=2)])])
    assert result["comparable_metric_count"] == 0
    assert result["changes"] == []


def test_share_comparison_requires_same_observation_date():
    cap = metric("mega7_market_cap_share", 20, subject_id="mega7", target_period="current")
    earnings = metric("mega7_forward_earnings_share", 15, subject_id="mega7", target_period="current", observation_date="2026-02-08")
    result = compare([source("yardeni", [cap, earnings])])
    assert not any("占标普市值" in line for line in result["brief_lines"])


def test_share_relation_is_derived_from_current_values():
    cap = metric("mega7_market_cap_share", 15, subject_id="mega7", target_period="current")
    earnings = metric("mega7_forward_earnings_share", 20, subject_id="mega7", target_period="forward_12m")
    result = compare([source("yardeni", [cap, earnings])])
    assert "市值份额低于盈利份额" in "".join(result["brief_lines"])
    assert "市值份额高于" not in "".join(result["brief_lines"])


def test_final_eps_is_not_compared_as_new_forecast_revision():
    old = metric("annual_eps:2025", 80, subject_id="sp500", estimate_status="estimate")
    actual = dict(old, value=82, estimate_status="final")
    result = compare([source("yardeni", [actual])], [source("yardeni", [old])])
    assert result["changes"] == []
    assert "最终值" in result["structure_rows"][0]["metric"]


def test_structured_locator_retains_page_and_reference():
    result = compare([source(metrics=[metric()])])
    assert "第 2 页" in result["sources"][0]["locator"]
    assert "REF-SYNTHETIC" in result["sector_rows"][0]["evidence"]
