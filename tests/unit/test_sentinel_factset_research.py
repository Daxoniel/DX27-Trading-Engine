"""Synthetic reports exercise source dates, periods, and honest missing data."""

from datetime import datetime, timezone
from hashlib import sha256
import os
from io import BytesIO
import stat

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from dx27.adapters.sentinel.factset_research import (
    LATEST_URL,
    SECTORS,
    fetch_factset,
    parse_pdf,
    parse_text,
)


NOW = datetime(2030, 7, 9, 13, tzinfo=timezone.utc)
KEYS = """EARNINGS INSIGHT
July 8, 2030
Key Metrics
Earnings Growth: For Q2 2030, the estimated (year-over-year) earnings growth rate for the S&P 500 is 4.2%.
The forward 12 -month P/E ratio for the S&P 500 is 17.3.
"""
GROWTH = """Earnings Growth: 4.2%
The estimated (year-over-year) earnings growth rate for Q2 2030 is 4.2%.
Revenue Growth: 2.7%
The estimated (year-over-year) revenue growth rate for Q 2 2030 is 2.7%.
For Q3 2030, analysts are projecting earnings growth of 7.8% and revenue growth of 4.5%.
For CY 2030, analysts are projecting earnings growth of 5.4% and revenue growth of 3.2%.
For CY 2031, analysts are projecting earnings growth of 8.9% and revenue growth of 6.4%.
"""


def revisions(*names, period="Q2 2030", baseline="March 31", both=False):
    text = f"""Earnings Revisions: Sector Estimate Changes
The estimated earnings growth rate for the S&P 500 for {period} is higher than at the start of the quarter ({baseline}).
"""
    for name in names:
        text += f"""{name}: Estimate Changes Since {baseline}
The {name} sector has recorded the largest percentage decrease in estimated (dollar -level) earnings of all eleven sectors since the start of the quarter at - 6.1% (to $9.39 billion from $10.00 billion).
This sector has also recorded an increase in price of 3.7% since {baseline}.
Overall, 8 of the 19 companies (42%) in the {name} sector have seen a decrease in their mean EPS estimate during this time.
"""
        if both:
            text += f"Overall, 5 of the 19 companies (26%) in the {name} sector have seen an increase in their mean EPS estimate during this time.\n"
    return text + "Index-Level EPS Estimate: Quarter Review\n"


def metric(result, metric_id, subject="sp500", period="Q2 2030"):
    return next(row for row in result["metrics"] if (
        row["metric_id"], row["subject_id"], row["target_period"]
    ) == (metric_id, subject, period))


def pdf(*pages):
    """Build actual text-bearing PDFs without a market-data fixture or renderer."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for text in pages:
        page = writer.add_blank_page(width=1200, height=1800)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = ["BT /F1 10 Tf 12 TL 20 1780 Td"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.append(f"({escaped}) Tj T*")
        content.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(content).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def test_forecast_periods_remain_separate_and_references_have_pdf_pages():
    result = parse_pdf(pdf(KEYS, revisions("Energy"), GROWTH), NOW)
    assert result["status"] == "PARTIAL"
    assert result["publication_date"] == "2030-07-08"
    assert metric(result, "earnings_growth_yoy")["value"] == 4.2
    assert metric(result, "revenue_growth_yoy")["value"] == 2.7
    assert metric(result, "earnings_growth_yoy", period="CY 2030")["value"] == 5.4
    assert metric(result, "earnings_growth_yoy", period="CY 2031")["value"] == 8.9
    assert metric(result, "forward_pe", period="FORWARD_12M")["unit"] == "ratio"
    entry = metric(result, "earnings_revision_pct", "energy")
    assert entry["value"] == -6.1
    assert entry["baseline_date"] == "2030-03-31"
    assert entry["observation_date"] == "2030-07-08"
    assert entry["reference_id"] == "REF-FACTSET-EI-20300708"
    assert entry["locator"]["page"] == 2


def test_sector_prices_and_counts_do_not_invent_opposite_revision_direction():
    result = parse_text([KEYS, revisions("Health Care", "Information Technology"), GROWTH], NOW)
    for subject in ("health_care", "information_technology"):
        assert metric(result, "price_change_pct", subject)["value"] == 3.7
        assert metric(result, "eps_down_count", subject)["value"] == 8
        assert metric(result, "eps_company_count", subject)["value"] == 19
        assert not any(m["subject_id"] == subject and m["metric_id"] == "eps_up_count" for m in result["metrics"])
    assert result["status"] == "PARTIAL"
    assert any("eps_up_count:health_care" in error for error in result["errors"])


def test_full_explicit_sector_coverage_is_available():
    result = parse_text([KEYS, revisions(*SECTORS, both=True), GROWTH], NOW)
    assert result["status"] == "AVAILABLE"
    assert result["errors"] == []
    assert {m["subject_id"] for m in result["metrics"]} == {"sp500", *SECTORS.values()}


def test_revision_sections_use_their_own_forecast_period_and_baseline():
    result = parse_text([
        KEYS,
        revisions("Energy", baseline="March 31"),
        revisions("Energy", period="Q3 2030", baseline="June 30"),
        GROWTH,
    ], NOW)
    assert metric(result, "earnings_revision_pct", "energy")["baseline_date"] == "2030-03-31"
    assert metric(result, "earnings_revision_pct", "energy", "Q3 2030")["baseline_date"] == "2030-06-30"
    assert metric(result, "price_change_pct", "energy", "Q3 2030")["locator"]["page"] == 3


def test_later_outlook_does_not_relabel_earlier_sector_revisions():
    text = revisions("Energy").replace(
        "Index-Level EPS Estimate:",
        "For Q3 2030, analysts expect further improvements.\nIndex-Level EPS Estimate:",
    )
    result = parse_text([KEYS, text, GROWTH], NOW)
    assert metric(result, "earnings_revision_pct", "energy")["value"] == -6.1
    assert not any(m["subject_id"] == "energy" and m["target_period"] == "Q3 2030" for m in result["metrics"])


def test_page_reference_tracks_the_value_when_a_sector_section_spans_pages():
    before, after = revisions("Energy").split("This sector", 1)
    result = parse_text([KEYS, before, "This sector" + after, GROWTH], NOW)
    assert metric(result, "earnings_revision_pct", "energy")["locator"]["page"] == 2
    assert metric(result, "price_change_pct", "energy")["locator"]["page"] == 3
    assert metric(result, "eps_down_count", "energy")["locator"]["page"] == 3


def test_absent_baseline_does_not_get_inferred_from_report_calendar():
    page = revisions("Energy").replace("(March 31)", "").replace("Since March 31", "Since Quarter Start").replace("since March 31", "since the start of the quarter")
    result = parse_text([KEYS, page, GROWTH], NOW)
    assert not any(m["subject_id"] == "energy" for m in result["metrics"])
    assert result["status"] == "PARTIAL"


def test_january_revision_baseline_rolls_back_only_from_printed_month_and_day():
    january = KEYS.replace("July 8, 2030", "January 8, 2030").replace("Q2 2030", "Q1 2030")
    result = parse_text([january, revisions("Energy", period="Q1 2030", baseline="December 31")], NOW)
    assert metric(result, "earnings_revision_pct", "energy", "Q1 2030")["baseline_date"] == "2029-12-31"


def test_future_publication_is_rejected_without_metrics():
    result = parse_pdf(pdf(KEYS.replace("July 8, 2030", "July 10, 2030"), GROWTH), NOW)
    assert result["status"] == "SOURCE_ERROR"
    assert result["metrics"] == []
    assert result["errors"] == ["PUBLICATION_DATE_AFTER_RETRIEVAL"]


def test_conflicting_values_are_abstained_instead_of_silently_overwritten():
    result = parse_text([KEYS, GROWTH, GROWTH.replace("rate for Q2 2030 is 4.2%", "rate for Q2 2030 is 5.1%")], NOW)
    assert result["status"] == "PARTIAL"
    assert not any(m["metric_id"] == "earnings_growth_yoy" and m["target_period"] == "Q2 2030" for m in result["metrics"])
    assert "CONFLICTING_VALUES:earnings_growth_yoy:sp500:Q2 2030" in result["errors"]


def test_capture_is_exact_private_and_refetch_is_not_replaced_by_old_success(tmp_path):
    payload = pdf(KEYS, revisions("Energy"), GROWTH)
    resolved = "https://advantage.factset.com/synthetic-report.pdf"
    calls = []

    def fetcher(url):
        calls.append(url)
        return payload, resolved, "application/pdf"

    capture_dir = tmp_path / "private-captures"
    first = fetch_factset(capture_dir, NOW, fetcher=fetcher)
    second = fetch_factset(capture_dir, NOW, fetcher=fetcher)
    assert calls == [LATEST_URL, LATEST_URL]
    assert first == second
    capture = first["captures"][0]
    path = capture_dir / capture["relative_path"]
    assert path.read_bytes() == payload
    assert capture["sha256"] == first["document_id"] == sha256(payload).hexdigest()
    if os.name != "nt":
        # Windows exposes readonly bits here; file access is controlled by ACLs.
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert capture["url"] == first["source_url"] == resolved

    def failed(url):
        raise TimeoutError("offline")

    unavailable = fetch_factset(capture_dir, NOW, fetcher=failed)
    assert unavailable["status"] == "SOURCE_ERROR"
    assert unavailable["metrics"] == unavailable["captures"] == []
    assert path.read_bytes() == payload


def test_fetch_rejects_html_and_captures_bad_pdf_as_a_failed_current_attempt(tmp_path):
    html = fetch_factset(tmp_path, NOW, fetcher=lambda url: b"<html>Sign in</html>")
    assert html["status"] == "SOURCE_ERROR"
    assert html["captures"] == []
    malformed = fetch_factset(tmp_path, NOW, fetcher=lambda url: b"%PDF-1.7\ninvalid")
    assert malformed["status"] == "SOURCE_ERROR"
    assert malformed["metrics"] == []
    assert len(malformed["captures"]) == 1
    assert malformed["errors"][0].startswith("PDF_EXTRACTION_FAILED:")


def test_existing_capture_integrity_failure_does_not_overwrite_or_use_old_values(tmp_path):
    payload = pdf(KEYS)
    destination = tmp_path / f"factset-{sha256(payload).hexdigest()}.pdf"
    destination.write_bytes(b"damaged")
    result = fetch_factset(tmp_path, NOW, fetcher=lambda url: payload)
    assert result["status"] == "SOURCE_ERROR"
    assert result["metrics"] == []
    assert destination.read_bytes() == b"damaged"


@pytest.mark.parametrize("pages", ["not a report", "EARNINGS INSIGHT\nDate not printed"])
def test_missing_document_identity_or_date_never_admits_values(pages):
    result = parse_text(pages, NOW)
    assert result["status"] == "SOURCE_ERROR"
    assert result["metrics"] == []


def test_aware_retrieval_watermark_is_required():
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_pdf(pdf(KEYS), datetime(2030, 7, 9))
