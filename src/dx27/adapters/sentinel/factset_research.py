"""Current public FactSet Earnings Insight, with explicit source abstentions.

Only values present in the downloaded report's text are admitted. Image-only
charts, absent revision directions, and unavailable sectors stay missing; a
previous capture is never used to fill a failed refresh.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import math
from pathlib import Path
import re
from typing import Callable, Sequence
from urllib.request import Request, urlopen


LATEST_URL = "https://www.factset.com/earningsinsight"
MAX_PDF_BYTES = 20 * 1024 * 1024
SECTORS = {
    "Energy": "energy",
    "Information Technology": "information_technology",
    "Health Care": "health_care",
    "Financials": "financials",
    "Materials": "materials",
    "Consumer Staples": "consumer_staples",
    "Consumer Discretionary": "consumer_discretionary",
    "Communication Services": "communication_services",
    "Industrials": "industrials",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
}
_MONTHS = {name: i for i, name in enumerate((
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
), 1)}
_MONTH = "(?:" + "|".join(_MONTHS) + ")"
_DATE = rf"({_MONTH})\s+(\d{{1,2}})(?:,?\s+(20\d{{2}}))?"
_NUMBER = r"[+\-]?\d+(?:\.\d+)?"
_PERIOD = r"(?:Q[1-4]|CY)\s+20\d{2}"
_SECTOR = "(?:" + "|".join(map(re.escape, SECTORS)) + ")"
_HEADING = re.compile(rf"(?m)^\s*({_SECTOR}):[^\n]*")


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FactSet retrieval watermark must be timezone-aware")
    return now.astimezone(timezone.utc)


def _result(now: datetime, source_url: str, document_id: str | None = None) -> dict:
    return {
        "source_id": "factset", "status": "SOURCE_ERROR",
        "retrieved_at": _utc(now).isoformat(), "publication_date": None,
        "source_url": source_url, "document_id": document_id,
        "metrics": [], "errors": [], "captures": [],
    }


def _clean(text: str, *, lines: bool = False) -> str:
    text = text.replace("\u2212", "-").replace("\u2011", "-").replace("\u00a0", " ")
    text = re.sub(r"\bQ\s+([1-4])", r"Q\1", text)
    text = re.sub(r"\b20\s*([0-9])\s*([0-9])\b", r"20\1\2", text)
    text = re.sub(r"(?<=\w)\s*-\s*(?=[A-Za-z])", "-", text)
    text = re.sub(r"(?<!\w)-\s+(?=\d)", "-", text)
    return re.sub(r"[^\S\n]+", " ", text) if lines else " ".join(text.split())


def _date_value(match: re.Match, publication: date) -> date | None:
    month = _MONTHS[match[1].title()]
    year = int(match[3]) if match[3] else publication.year
    try:
        value = date(year, month, int(match[2]))
        if not match[3] and value > publication:
            value = date(year - 1, month, int(match[2]))
        return value if value <= publication else None
    except ValueError:
        return None


def _baseline(text: str, publication: date) -> date | None:
    patterns = (
        rf"(?:since|compared to)\s+{_DATE}",
        rf"start of the quarter\s*\(\s*{_DATE}\s*\)",
        rf"from\s+{_DATE}\s+to\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _date_value(match, publication)
    return None


def _flatten_with_offsets(text: str) -> tuple[str, list[int]]:
    parts, offsets = [], []
    for token in re.finditer(r"\S+", text):
        if parts:
            parts.append(" ")
            offsets.append(token.start() - 1)
        parts.append(token[0])
        offsets.extend(range(token.start(), token.end()))
    return "".join(parts), offsets


def _sentence_period(text: str, start: int, default: str) -> str:
    # A subsequent outlook sentence must not relabel an earlier revision.
    sentence_start = text.rfind(". ", 0, start) + 2
    match = re.search(_PERIOD, text[max(0, sentence_start):start])
    return match[0].upper() if match else default


def parse_text(
    pages: str | Sequence[str], now: datetime, *, source_url: str = LATEST_URL,
    document_id: str | None = None,
) -> dict:
    """Parse extracted pages; useful for deterministic source-format tests.

    Every forecast carries its own quarter/calendar-year label. Revisions use
    the period in the revision section and its explicitly printed baseline,
    rather than the calendar quarter in which the report was downloaded.
    """
    page_texts = [pages] if isinstance(pages, str) else list(pages)
    result = _result(now, source_url, document_id)
    if not page_texts or "EARNINGS INSIGHT" not in page_texts[0].upper():
        result["errors"].append("UNRECOGNIZED_EARNINGS_INSIGHT_DOCUMENT")
        return result
    stamp = re.search(_DATE, _clean(page_texts[0]), re.I)
    if stamp is None or not stamp[3]:
        result["errors"].append("PUBLICATION_DATE_MISSING")
        return result
    try:
        publication = date(int(stamp[3]), _MONTHS[stamp[1].title()], int(stamp[2]))
    except ValueError:
        result["errors"].append("PUBLICATION_DATE_INVALID")
        return result
    result["publication_date"] = publication.isoformat()
    if publication > _utc(now).date():
        result["errors"].append("PUBLICATION_DATE_AFTER_RETRIEVAL")
        return result
    reference = "REF-FACTSET-EI-" + publication.strftime("%Y%m%d")
    normalized = [_clean(page, lines=True) for page in page_texts]
    joined = "\n".join(normalized)
    offsets, position = [], 0
    for page in normalized:
        offsets.append(position)
        position += len(page) + 1
    metrics: dict[tuple, dict] = {}
    conflicts: set[tuple] = set()

    def add(metric_id, subject, value, period, at, section, baseline=None):
        value = float(value)
        if not math.isfinite(value):
            return
        baseline_iso = baseline.isoformat() if baseline else None
        key = (metric_id, subject, period, baseline_iso)
        if key in conflicts:
            return
        if key in metrics and metrics[key]["value"] != value:
            del metrics[key]
            conflicts.add(key)
            result["errors"].append(f"CONFLICTING_VALUES:{metric_id}:{subject}:{period}")
            return
        unit = "count" if metric_id.endswith("_count") else "ratio" if metric_id == "forward_pe" else "percent"
        entry = {
            "metric_id": metric_id, "subject_id": subject,
            "label": metric_id.replace("_", " "), "value": value,
            "unit": unit, "target_period": period,
            "observation_date": publication.isoformat(),
            "reference_id": reference,
            "locator": {"page": bisect_right(offsets, at), "section": section},
        }
        if baseline_iso:
            entry["baseline_date"] = baseline_iso
        metrics.setdefault(key, entry)

    current_match = re.search(
        rf"Earnings Growth:\s*For\s+({_PERIOD})\s*,", _clean(page_texts[0]), re.I,
    )
    # Editions may omit the key-metrics prefix but still state the same explicit
    # period in their earnings-growth paragraph.
    if not current_match:
        current_match = re.search(
            rf"(?:estimated|blended).{{0,50}}earnings growth rate for\s+({_PERIOD})\s+is", joined, re.I,
        )
    current_period = _clean(current_match[1]).upper() if current_match else None
    for metric, noun in (("earnings_growth_yoy", "earnings"), ("revenue_growth_yoy", "revenue")):
        patterns = (
            rf"For\s+({_PERIOD})\s*,\s*the\s+(?:estimated|blended).{{0,60}}?{noun} growth rate for the S&P 500 is\s+({_NUMBER})%",
            rf"(?:estimated|blended).{{0,60}}?{noun} growth rate for\s+({_PERIOD})\s+is\s+({_NUMBER})%",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, joined, re.I | re.S):
                add(metric, "sp500", match[2], _clean(match[1]).upper(), match.start(), f"{noun.title()} Growth")
    # Forward summaries bind both values to the period in that sentence; annual
    # forecasts are never admitted as current-quarter estimates.
    projection = re.compile(
        rf"For\s+({_PERIOD})\s*,\s*analysts\s+(?:are\s+)?(?:projecting|predicting|calling for)\s+"
        rf"(?:\(year-over-year\)\s+)?earnings growth of\s+({_NUMBER})%"
        rf"(?:\s+and\s+revenue growth of\s+({_NUMBER})%)?", re.I,
    )
    for match in projection.finditer(joined):
        period = _clean(match[1]).upper()
        add("earnings_growth_yoy", "sp500", match[2], period, match.start(), "Forward Estimates")
        if match[3] is not None:
            add("revenue_growth_yoy", "sp500", match[3], period, match.start(), "Forward Estimates")
    for match in re.finditer(
        rf"forward 12-month P/E ratio(?: for the S&P 500)? is\s+({_NUMBER})", joined, re.I,
    ):
        add("forward_pe", "sp500", match[1], "FORWARD_12M", match.start(), "Valuation")

    # Only prose inside the explicitly named revision section is considered.
    # Topic-of-the-week, forward EPS revisions, and price targets do not inherit
    # the main earnings season's period or baseline.
    for heading in re.finditer(r"(?m)^\s*Earnings Revisions:[^\n]*", joined):
        end = re.search(r"(?m)^\s*(?:Index-Level EPS Estimate|Earnings Guidance|Earnings Growth):", joined[heading.end():])
        stop = heading.end() + end.start() if end else len(joined)
        section = joined[heading.start():stop]
        sector_headings = list(_HEADING.finditer(section))
        preamble = _clean(section[:sector_headings[0].start()] if sector_headings else section)
        period_match = re.search(_PERIOD, preamble)
        if not period_match:
            result["errors"].append("REVISION_TARGET_PERIOD_MISSING")
            continue
        revision_period = period_match[0].upper()
        section_baseline = _baseline(preamble, publication)
        for unchanged in re.finditer(
            rf"sector\s*\(({_SECTOR})\)\s+has seen no change in (?:expected|estimated)\s+earnings[^.]*",
            preamble, re.I,
        ):
            base = _baseline(unchanged[0], publication) or section_baseline
            if base:
                name = next(name for name in SECTORS if name.lower() == unchanged[1].lower())
                add("earnings_revision_pct", SECTORS[name], 0, revision_period, heading.start(), "Earnings Revisions", base)
        for i, sector_heading in enumerate(sector_headings):
            block_end = sector_headings[i + 1].start() if i + 1 < len(sector_headings) else len(section)
            block = section[sector_heading.start():block_end]
            block_flat, block_offsets = _flatten_with_offsets(block)
            subject = SECTORS[sector_heading[1]]
            local_period = re.search(_PERIOD, sector_heading[0])
            period = local_period[0].upper() if local_period else revision_period
            base = _baseline(block_flat, publication) or section_baseline
            location = heading.start() + sector_heading.start()
            earnings = re.search(
                rf"(?:percentage\s+)?(increase|decrease) in estimated\s+\(dollar-level\)\s+"
                rf"earnings.{{0,150}}?since the start of the quarter at\s+({_NUMBER})%", block_flat, re.I,
            )
            if earnings and base:
                value = abs(float(earnings[2])) * (-1 if earnings[1].lower() == "decrease" else 1)
                add("earnings_revision_pct", subject, value, _sentence_period(block_flat, earnings.start(), period),
                    location + block_offsets[earnings.start()], "Earnings Revisions", base)
            elif re.search(r"(?:no change|unchanged) in (?:expected|estimated).*?earnings", block_flat, re.I) and base:
                add("earnings_revision_pct", subject, 0, period, location, "Earnings Revisions", base)
            price = re.search(
                rf"(?:This|the) sector has (?:also )?recorded.{{0,80}}?(increase|decrease) in price"
                rf".{{0,100}}?({_NUMBER})%[^.]*", block_flat, re.I,
            )
            if price:
                price_base = _baseline(price[0], publication) or base
                if price_base:
                    value = abs(float(price[2])) * (-1 if price[1].lower() == "decrease" else 1)
                    add("price_change_pct", subject, value, _sentence_period(block_flat, price.start(), period),
                        location + block_offsets[price.start()], "Earnings Revisions", price_base)
            counts = re.finditer(
                rf"(?:Overall,\s*)?(\d+)\s+of\s+(?:the\s+)?(\d+)\s+companies\s*(?:\([^)]*\))?\s*"
                rf"in the\s+{re.escape(sector_heading[1])}\s+sector have seen\s+(?:a\s*n?\s*|an\s+)"
                rf"(increase|decrease) in their mean EPS estimate", block_flat, re.I,
            )
            for count in counts:
                numerator, total = int(count[1]), int(count[2])
                if numerator > total or not base:
                    result["errors"].append(f"INVALID_OR_UNDATED_EPS_COUNT:{subject}:{period}")
                    continue
                direction = "eps_up_count" if count[3].lower() == "increase" else "eps_down_count"
                count_period = _sentence_period(block_flat, count.start(), period)
                at = location + block_offsets[count.start()]
                add(direction, subject, numerator, count_period, at, "Earnings Revisions", base)
                add("eps_company_count", subject, total, count_period, at, "Earnings Revisions", base)

    result["metrics"] = list(metrics.values())
    required = {("forward_pe", "sp500", "FORWARD_12M")}
    if current_period:
        required.update((metric, "sp500", current_period) for metric in ("earnings_growth_yoy", "revenue_growth_yoy"))
        required.update((metric, subject, current_period) for subject in SECTORS.values() for metric in (
            "earnings_revision_pct", "price_change_pct", "eps_up_count", "eps_down_count", "eps_company_count",
        ))
    else:
        result["errors"].append("CURRENT_QUARTER_PERIOD_MISSING")
    admitted = {(m["metric_id"], m["subject_id"], m["target_period"]) for m in result["metrics"]}
    missing = sorted(required - admitted)
    if missing:
        result["errors"].append("MISSING_TEXT_METRICS:" + ",".join(":".join(key) for key in missing))
    if not result["metrics"]:
        result["errors"].append("NO_USABLE_TEXT_METRICS")
    else:
        result["status"] = "PARTIAL" if result["errors"] else "AVAILABLE"
    return result


def parse_pdf(payload: bytes, now: datetime, *, source_url: str = LATEST_URL) -> dict:
    """Extract text from a newly retrieved PDF without substituting old data."""
    result = _result(now, source_url, sha256(payload).hexdigest())
    if not payload.startswith(b"%PDF-") or len(payload) > MAX_PDF_BYTES:
        result["errors"].append("INVALID_OR_OVERSIZED_PDF")
        return result
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(payload))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 150:
            raise ValueError("encrypted or unexpected PDF page count")
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        result["errors"].append(f"PDF_EXTRACTION_FAILED:{type(exc).__name__}")
        return result
    return parse_text(pages, now, source_url=source_url, document_id=result["document_id"])


def _download(url: str) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": "DX27-Research/1.0", "Accept": "application/pdf"})
    with urlopen(request, timeout=35) as response:
        payload = response.read(MAX_PDF_BYTES + 1)
        return payload, response.geturl(), response.headers.get_content_type()


def fetch_factset(
    capture_dir: Path, now: datetime, *, fetcher: Callable | None = None,
) -> dict:
    """Fetch the latest endpoint and save the exact bytes in a private directory.

    An injected ``fetcher(url)`` returns bytes or ``(bytes, resolved_url,
    content_type)``. It is deliberately invoked on every refresh.
    """
    result = _result(now, LATEST_URL)
    try:
        downloaded = (fetcher or _download)(LATEST_URL)
        payload, url, content_type = (downloaded, LATEST_URL, "application/pdf") if isinstance(downloaded, bytes) else downloaded
        if not isinstance(payload, bytes) or len(payload) > MAX_PDF_BYTES:
            raise ValueError("invalid or oversized FactSet response")
        if not payload.startswith(b"%PDF-"):
            raise ValueError("latest endpoint did not return a PDF")
        digest = sha256(payload).hexdigest()
        private_dir = Path(capture_dir)
        private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        relative = f"factset-{digest}.pdf"
        path = private_dir / relative
        # Exclusive creation avoids following a pre-existing destination link.
        try:
            with path.open("xb") as stream:
                stream.write(payload)
            path.chmod(0o600)
        except FileExistsError:
            if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("FactSet capture integrity failure")
        result = parse_pdf(payload, now, source_url=url)
        result["captures"] = [{
            "sha256": digest, "relative_path": relative, "url": url,
            "content_type": content_type,
        }]
        return result
    except Exception as exc:
        result["errors"].append(f"FACTSET_FETCH_FAILED:{type(exc).__name__}")
        return result
