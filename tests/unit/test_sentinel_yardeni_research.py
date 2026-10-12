"""Synthetic legends only: no captured source images or market values."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import math

import pytest

from dx27.adapters.sentinel.yardeni_research import (
    CHARTS,
    SECTORS,
    fetch_yardeni,
    parse_chart,
)


NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def line(text, *, x=10, y=20, confidence=0.98):
    return [[[x, y], [x + 400, y], [x + 400, y + 20], [x, y + 20]], text, confidence]


def year_axis():
    return [line("2025", x=10, y=500), line("2026", x=500, y=500)]


def share_lines():
    return [
        line("Mag-7 Share of S&P 500 Capitalization (Oct 09 = 10.0)", y=20),
        line("Mag-7ShareofS&P500ForwardEarnings(Oct09=8.0)", y=50),
        line("Mag-7 Share of S&P 500 Forward Revenues (Oct 09 = 4.0)", y=80),
        *year_axis(),
    ]


def eps_lines():
    return [
        line("Consensus Forward EPS* (10/08/26 = 130.00)", y=20),
        line("Consensus2025EPS(Final=99.00)", y=50),
        line("Consensus 2026 EPS (10/08/26 = 125.00)", y=80),
        line("Consensus 2027 EPS (10/08/26 = 140.00)", y=110),
        line("Consensus 2028 EPS (10/08/26 = 155.00)", y=140),
    ]


def neri_lines():
    return [
        line(f"{label.title()} NERI* (Oct = {index - 5}.0)", y=20 + index * 30)
        for index, label in enumerate(SECTORS)
    ] + [line("040608101214161820222426", y=500)]


def total_earnings_lines():
    return [
        line("S&P 500 (Oct 01 = 1,500.0)", y=20),
        line("S&P 500 ex-Magnificent-7* (Oct 01 = 1,000.0)", y=50),
        line("Magnificent-7* (Oct 09 = 510.0)", y=80),
        *year_axis(),
    ]


def parse(kind, items, **kwargs):
    return parse_chart(kind, items, now=NOW, reference_id="synthetic-sha", locator="synthetic figure", **kwargs)


def sources():
    payloads, detections = {}, {}
    pages = {}
    legends = {
        "mega7_shares": share_lines(),
        "sector_neri": neri_lines(),
        "sp500_eps": eps_lines(),
        "group_forward_earnings": total_earnings_lines(),
    }
    for index, spec in enumerate(CHARTS):
        image_url = f"https://product.datastream.com/dscharting/gateway.aspx?guid=synthetic-{index}&action=REFRESH"
        charts = pages.setdefault(spec.page_url, [])
        while len(charts) < spec.figure:
            charts.append({"title": "UNUSED SYNTHETIC FIGURE", "subtitle": "", "imageUrl": image_url})
        subtitle = "(billion dollars, weekly, ratio scale)" if spec.chart_id == "group_forward_earnings" else "(as of Oct 01, 2026)"
        charts[spec.figure - 1] = {"title": " ".join(spec.title_terms), "subtitle": subtitle, "imageUrl": image_url}
        image = b"\x89PNG\r\n\x1a\n" + f"SYNTHETIC IMAGE {index}".encode()
        payloads[image_url] = image
        detections[image] = legends[spec.chart_id]
    for page_url, charts in pages.items():
        chunk = json.dumps({"charts": charts})
        payloads[page_url] = ("<html><script>self.__next_f.push(" + json.dumps([1, chunk]) + ")</script></html>").encode()
    return payloads, detections


def test_fetches_four_current_charts_and_records_exact_captures(tmp_path):
    payloads, detections = sources()
    requested = []

    def fetch(url):
        requested.append(url)
        return payloads[url]

    result = fetch_yardeni(tmp_path, NOW, fetcher=fetch, ocr=detections.__getitem__)
    assert result["status"] == "AVAILABLE"
    assert result["source_id"] == "yardeni"
    assert result["publication_date"] is None
    assert result["retrieved_at"] == NOW.isoformat()
    assert result["errors"] == []
    assert len(result["metrics"]) == 23
    assert len(requested) == 7
    assert requested.count(CHARTS[2].page_url) == 1
    assert len(result["captures"]) == 7
    for capture in result["captures"]:
        saved = (tmp_path / capture["relative_path"]).read_bytes()
        assert saved == payloads[capture["url"]]
        assert sha256(saved).hexdigest() == capture["sha256"]
    for metric in result["metrics"]:
        assert math.isfinite(metric["value"])
        assert metric["ocr_confidence"] >= 0.90
        assert "printed legend:" in metric["locator"]
        assert metric["reference_id"].startswith("REF-YARDENI-")
        assert metric["reference_id"].rsplit("-", 1)[-1] in {capture["sha256"][:16] for capture in result["captures"]}


def test_same_document_has_stable_identity_even_at_a_later_capture_time(tmp_path):
    payloads, detections = sources()
    first = fetch_yardeni(tmp_path, NOW, fetcher=payloads.__getitem__, ocr=detections.__getitem__)
    second = fetch_yardeni(tmp_path, NOW.replace(hour=13), fetcher=payloads.__getitem__, ocr=detections.__getitem__)
    assert first["document_id"] == second["document_id"]
    assert first["retrieved_at"] != second["retrieved_at"]


def test_eps_keeps_fixed_calendar_forecasts_separate_from_rolling_eps_and_final():
    metrics, errors = parse("sp500_eps", eps_lines())
    assert errors == []
    by_id = {metric["metric_id"]: metric for metric in metrics}
    assert by_id["annual_eps:2026"]["target_period"] == "2026"
    assert by_id["annual_eps:2026"]["estimate_status"] == "forecast"
    assert by_id["forward_eps"]["target_period"] == "forward_12m"
    assert by_id["forward_eps"]["observation_date"] == "2026-10-08"
    assert by_id["annual_eps:2025"]["estimate_status"] == "final"
    assert by_id["annual_eps:2025"]["observation_date"] is None
    assert by_id["annual_eps:2025"]["date_precision"] == "unknown"


def test_neri_is_three_month_revision_breadth_with_month_precision():
    metrics, errors = parse("sector_neri", neri_lines(), context_years={2026})
    assert errors == []
    assert len(metrics) == 12
    assert {metric["subject_id"] for metric in metrics} == set(SECTORS.values())
    assert all(metric["unit"] == "percent" for metric in metrics)
    assert all(metric["target_period"] == "rolling_3m" for metric in metrics)
    assert all(metric["observation_date"] is None for metric in metrics)
    assert all(metric["observation_period"] == "2026-10" for metric in metrics)
    assert all(metric["date_precision"] == "month" for metric in metrics)
    assert all("estimates up minus estimates down" in metric["definition"] for metric in metrics)


def test_forward_total_earnings_are_aggregate_billions_for_three_groups():
    metrics, errors = parse("group_forward_earnings", total_earnings_lines())
    assert errors == []
    assert {metric["subject_id"] for metric in metrics} == {"sp500", "sp493", "mega7"}
    assert all(metric["metric_id"] == "forward_total_earnings" for metric in metrics)
    assert all(metric["unit"] == "USD_billions" for metric in metrics)
    assert all(metric["target_period"] == "forward_12m" for metric in metrics)
    assert all("not earnings per share" in metric["definition"] for metric in metrics)
    assert {metric["subject_id"]: metric["value"] for metric in metrics} == {"sp500": 1500, "sp493": 1000, "mega7": 510}


def test_forward_total_earnings_keep_different_group_dates_independently():
    metrics, errors = parse("group_forward_earnings", total_earnings_lines())
    assert errors == []
    assert {metric["subject_id"]: metric["observation_date"] for metric in metrics} == {
        "sp500": "2026-10-01", "sp493": "2026-10-01", "mega7": "2026-10-09",
    }
    assert len(metrics) == 3
    assert all("share" not in metric["metric_id"] for metric in metrics)


def test_future_total_earnings_are_rejected_without_losing_other_group_readings():
    items = total_earnings_lines()
    items[2] = line("Magnificent-7* (Oct 13 = 510.0)", y=80)
    metrics, errors = parse("group_forward_earnings", items)
    assert {metric["subject_id"] for metric in metrics} == {"sp500", "sp493"}
    assert any("future-dated observation" in error for error in errors)


def test_month_only_date_needs_year_evidence_instead_of_capture_date():
    metrics, errors = parse("sector_neri", neri_lines())
    assert metrics == []
    assert errors and all("year is unknown" in error for error in errors)


def test_month_day_year_needs_a_printed_axis_if_year_is_not_explicit():
    metrics, errors = parse("mega7_shares", share_lines()[:3])
    assert metrics == []
    assert all("year is unknown" in error for error in errors)


def test_future_observations_are_omitted_and_others_remain():
    items = eps_lines()
    items[0] = line("Consensus Forward EPS* (10/13/26 = 130.00)")
    metrics, errors = parse("sp500_eps", items)
    assert "forward_eps" not in {metric["metric_id"] for metric in metrics}
    assert len(metrics) == 4
    assert any("future-dated" in error for error in errors)


def test_neri_future_month_is_rejected_even_without_a_day():
    metrics, errors = parse("sector_neri", [line("Energy NERI* (Nov = 5.0)"), *year_axis()])
    assert metrics == []
    assert any("future-dated observation month" in error for error in errors)


def test_low_confidence_and_unbound_numbers_never_become_values():
    items = share_lines()
    items[1] = line("Mag-7 Share of S&P 500 Forward Earnings (Oct 09 = 8.0)", y=50, confidence=0.89)
    items += [line("8.0", y=200), line("Oct 09", y=230), line("Unknown series (Oct 09 = 8.0)", y=260)]
    metrics, _ = parse("mega7_shares", items)
    assert {metric["metric_id"] for metric in metrics} == {"mega7_market_cap_share", "mega7_forward_revenues_share"}


@pytest.mark.parametrize("value", ["101.0", "-1.0", "1,000.0"])
def test_share_values_must_be_percentages(value):
    metrics, errors = parse("mega7_shares", [line(f"Mag-7 Share of S&P 500 Capitalization (Oct 09 = {value})"), *year_axis()])
    assert metrics == []
    assert any("outside metric range" in error for error in errors)


def test_ocr_never_repairs_numeric_characters():
    metrics, _ = parse("sector_neri", [line("Communication Services NERl* (Oct = 0.o)"), *year_axis()])
    assert metrics == []
    valid, _ = parse("sector_neri", [line("CommunicationServicesNERl*(Oct=0.0)"), *year_axis()])
    assert valid[0]["value"] == 0


def test_full_width_ocr_parentheses_preserve_verified_numeric_values():
    metrics, errors = parse("sp500_eps", [line("Consensus2028EPS（10/08/26=155.00)")])
    assert errors == []
    assert metrics[0]["metric_id"] == "annual_eps:2028"
    assert metrics[0]["value"] == 155


def test_duplicate_legend_binding_is_ambiguous_even_if_values_match():
    items = [*share_lines(), line("Mag-7 Share of S&P 500 Capitalization (Oct 09 = 10.0)", y=200)]
    metrics, errors = parse("mega7_shares", items)
    assert "mega7_market_cap_share" not in {metric["metric_id"] for metric in metrics}
    assert any("ambiguous duplicate" in error for error in errors)


def test_three_shares_with_inconsistent_dates_do_not_form_one_observation():
    items = share_lines()
    items[1] = line("Mag-7 Share of S&P 500 Forward Earnings (Oct 08 = 8.0)", y=50)
    metrics, errors = parse("mega7_shares", items)
    assert metrics == []
    assert any("inconsistent observation dates" in error for error in errors)


def test_one_failed_page_preserves_other_sources_and_marks_partial(tmp_path):
    payloads, detections = sources()
    del payloads[CHARTS[0].page_url]
    result = fetch_yardeni(tmp_path, NOW, fetcher=payloads.__getitem__, ocr=detections.__getitem__)
    assert result["status"] == "PARTIAL"
    assert len(result["metrics"]) == 20
    assert any("mega7_shares" in error for error in result["errors"])


def test_missing_ocr_is_an_explicit_source_error(tmp_path):
    payloads, _ = sources()

    def unavailable(_):
        raise RuntimeError("OCR unavailable")

    result = fetch_yardeni(tmp_path, NOW, fetcher=payloads.__getitem__, ocr=unavailable)
    assert result["status"] == "SOURCE_ERROR"
    assert result["metrics"] == []
    assert len(result["captures"]) == 7
    assert any("OCR unavailable" in error for error in result["errors"])


def test_unexpected_figure_identity_does_not_fetch_a_wrong_chart(tmp_path):
    payloads, detections = sources()
    payloads[CHARTS[0].page_url] = payloads[CHARTS[0].page_url].replace(b"MARKET CAP", b"SOME OTHER SERIES")
    result = fetch_yardeni(tmp_path, NOW, fetcher=payloads.__getitem__, ocr=detections.__getitem__)
    assert result["status"] == "PARTIAL"
    assert any("figure identity changed" in error for error in result["errors"])


def test_unexpected_image_host_is_rejected(tmp_path):
    payloads, detections = sources()
    payloads[CHARTS[0].page_url] = payloads[CHARTS[0].page_url].replace(b"product.datastream.com", b"unrelated.invalid")
    result = fetch_yardeni(tmp_path, NOW, fetcher=payloads.__getitem__, ocr=detections.__getitem__)
    assert any("unexpected chart source URL" in error for error in result["errors"])


def test_retrieval_time_requires_timezone(tmp_path):
    with pytest.raises(ValueError, match="timezone aware"):
        fetch_yardeni(tmp_path, NOW.replace(tzinfo=None))
