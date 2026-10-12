"""Capture four public Yardeni charts and read only their printed legends.

The new Yardeni site serves Datastream images, not a numeric data API.  OCR is
therefore deliberately conservative: chart lines and point coordinates never
become values.  Dates describe observations, not a report publication date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from threading import Lock
from typing import Callable, Iterable
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


MAG7_URL = (
    "https://yardeni.com/charts/us-stock-market/"
    "stock-market-investment-styles/magnificent-7"
)
SECTORS_URL = (
    "https://yardeni.com/charts/us-stock-market/"
    "stock-market-forward-metrics/sp-500-sectors-forward-metrics-fundamentals"
)
EPS_URL = (
    "https://yardeni.com/charts/yardeni-university/in-10-charts/"
    "sp-msci-forward-earnings"
)
MIN_CONFIDENCE = 0.90
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        1,
    )
}
SECTORS = {
    "s&p 500": "sp500",
    "communication services": "communication_services",
    "consumer discretionary": "consumer_discretionary",
    "consumer staples": "consumer_staples",
    "energy": "energy",
    "financials": "financials",
    "health care": "health_care",
    "industrials": "industrials",
    "information technology": "information_technology",
    "materials": "materials",
    "real estate": "real_estate",
    "utilities": "utilities",
}


@dataclass(frozen=True)
class ChartSpec:
    chart_id: str
    page_url: str
    figure: int
    title_terms: tuple[str, ...]
    expected_metrics: int


CHARTS = (
    ChartSpec("mega7_shares", MAG7_URL, 2, ("SHARE", "MARKET CAP", "FORWARD EARNINGS", "FORWARD REVENUES"), 3),
    ChartSpec("sector_neri", SECTORS_URL, 10, ("SECTORS", "NET EARNINGS REVISIONS INDEXES"), 12),
    ChartSpec("sp500_eps", EPS_URL, 1, ("S&P 500", "OPERATING EARNINGS PER SHARE"), 5),
    ChartSpec("group_forward_earnings", EPS_URL, 6, ("FORWARD EARNINGS", "S&P 500", "S&P 493", "MAGNIFICENT-7"), 3),
)


@dataclass(frozen=True)
class OCRLine:
    """Text, its confidence, and image coordinates returned by RapidOCR."""

    text: str
    confidence: float
    box: tuple[tuple[float, float], ...]

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = zip(*self.box)
        return min(xs), min(ys), max(xs), max(ys)


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        self.in_script = tag == "script"

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)


def _chart_metadata(payload: bytes) -> list[dict]:
    parser = _Scripts()
    parser.feed(payload.decode("utf-8"))
    decoder = json.JSONDecoder()
    for script in parser.scripts:
        for match in re.finditer(r"self\.__next_f\.push\(", script):
            try:
                chunk, _ = decoder.raw_decode(script, match.end())
            except ValueError:
                continue
            if not isinstance(chunk, list) or len(chunk) < 2 or not isinstance(chunk[1], str):
                continue
            for charts in re.finditer(r'"charts"\s*:\s*(\[)', chunk[1]):
                try:
                    rows, _ = decoder.raw_decode(chunk[1], charts.start(1))
                except ValueError:
                    continue
                if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
                    return rows
    raise ValueError("official page has no readable chart metadata")


def _allowed_url(url: str, *, image: bool = False) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return False
    return (
        parts.hostname == "product.datastream.com"
        and parts.path.lower() == "/dscharting/gateway.aspx"
        if image
        else parts.hostname == "yardeni.com" and parts.path.startswith("/charts/")
    )


def _fetch(url: str) -> tuple[bytes, str]:
    image = urlsplit(url).hostname == "product.datastream.com"
    if not _allowed_url(url, image=image):
        raise ValueError("unexpected source URL")
    request = Request(
        quote(url, safe=":/?&=%"),
        headers={"User-Agent": "DX27-Sentinel-Research/1.0", "Accept": "image/*" if image else "text/html"},
    )
    with urlopen(request, timeout=25) as response:
        if not _allowed_url(response.url, image=image):
            raise ValueError("unexpected source redirect")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        content_type = response.headers.get_content_type()
    if not payload or len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("empty or oversized source response")
    return payload, content_type


_ocr_engine = None
_ocr_lock = Lock()


def _ocr(payload: bytes) -> list:
    """Use packaged ONNX models; no system OCR executable is required."""
    global _ocr_engine
    try:
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError("install the research-report extra for Yardeni chart OCR") from exc
    pixels = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ValueError("chart response is not a decodable image")
    height, width = pixels.shape[:2]
    # These three official layouts have printed legend regions. Excluding the
    # colored samples improves text recognition and avoids processing curves.
    # A changed layout produces missing legends, not inferred chart values.
    if height / width > 0.95:
        regions = [
            (left, 0.032 + row * 0.159, right, 0.074 + row * 0.159)
            for row in range(6)
            for left, right in ((0.071, 0.49), (0.574, 0.98))
        ] + [(0.022, 0.95, 0.49, 0.971), (0.52, 0.95, 0.98, 0.971)]
    else:
        regions = [(0.04, 0.13, 0.56, 0.285), (0.032, 0.89, 0.98, 0.94)]
    crops = []
    mappings = []
    canvas_y = 0
    for left, top, right, bottom in regions:
        x0, y0, x1, y1 = int(left * width), int(top * height), int(right * width), int(bottom * height)
        crop = pixels[y0:y1, x0:x1]
        crops.append(crop)
        mappings.append((canvas_y, canvas_y + crop.shape[0], x0, y0))
        canvas_y += crop.shape[0] + 12
    canvas = np.full((canvas_y, max(crop.shape[1] for crop in crops), 3), 255, dtype=np.uint8)
    for crop, (top, bottom, _, _) in zip(crops, mappings):
        canvas[top:bottom, :crop.shape[1]] = crop
    with _ocr_lock:
        if _ocr_engine is None:
            _ocr_engine = RapidOCR(
                det_limit_side_len=2200,
                det_limit_type="max",
                intra_op_num_threads=1,
                inter_op_num_threads=1,
            )
        result, _ = _ocr_engine(canvas)
    restored = []
    for box, text, confidence in result or []:
        center_y = sum(point[1] for point in box) / len(box)
        for top, bottom, x0, y0 in mappings:
            if top <= center_y < bottom:
                restored.append([[[point[0] + x0, point[1] - top + y0] for point in box], text, confidence])
                break
    return restored


def _lines(items: Iterable) -> list[OCRLine]:
    lines = []
    for item in items:
        try:
            if isinstance(item, OCRLine):
                line = item
            elif isinstance(item, dict):
                line = OCRLine(str(item["text"]), float(item["confidence"]), tuple(tuple(float(v) for v in p) for p in item["box"]))
            else:
                box, text, confidence = item
                line = OCRLine(str(text), float(confidence), tuple(tuple(float(v) for v in p) for p in box))
            if (
                len(line.box) >= 4
                and all(len(point) == 2 and all(math.isfinite(v) for v in point) for point in line.box)
                and math.isfinite(line.confidence)
                and MIN_CONFIDENCE <= line.confidence <= 1
                and line.text.strip()
            ):
                lines.append(line)
        except (ValueError, TypeError, KeyError):
            continue
    return lines


def _joined_lines(lines: list[OCRLine]) -> list[OCRLine]:
    """Join adjacent fragments on one baseline, never across chart panels."""
    pending = sorted(lines, key=lambda line: (line.bounds[1], line.bounds[0]))
    result = []
    while pending:
        current = pending.pop(0)
        while True:
            x0, y0, x1, y1 = current.bounds
            candidates = []
            for index, other in enumerate(pending):
                ox0, oy0, ox1, oy1 = other.bounds
                overlap = min(y1, oy1) - max(y0, oy0)
                height = min(y1 - y0, oy1 - oy0)
                gap = ox0 - x1
                if height > 0 and overlap / height >= 0.7 and 0 <= gap <= max(48, height * 2):
                    candidates.append((gap, index))
            if not candidates:
                break
            _, index = min(candidates)
            other = pending.pop(index)
            ox0, oy0, ox1, oy1 = other.bounds
            current = OCRLine(
                current.text + " " + other.text,
                min(current.confidence, other.confidence),
                ((x0, min(y0, oy0)), (ox1, min(y0, oy0)), (ox1, max(y1, oy1)), (x0, max(y1, oy1))),
            )
        result.append(current)
    return result


def _axis_year(lines: list[OCRLine], *, context_years: set[int]) -> int | None:
    """Read printed year ticks. Two-digit ticks require explicit page century evidence."""
    numeric_rows: list[tuple[float, float, list[int]]] = []
    for line in lines:
        if re.fullmatch(r"\d{2,}(?:\s+\d{2,})*", line.text.strip()):
            x0, y0, _, _ = line.bounds
            values = []
            for text in line.text.split():
                if len(text) == 4 and 2000 <= int(text) <= 2099:
                    values.append(int(text))
                elif len(text) % 2 == 0:
                    values.extend(int(text[i:i + 2]) for i in range(0, len(text), 2))
            numeric_rows.append((x0, y0, values))
    full_years = [(x, y, value) for x, y, values in numeric_rows for value in values if 2000 <= value <= 2099]
    if len({value for _, _, value in full_years}) >= 2:
        # A chronological axis must ascend from left to right; vertical value
        # axes and unlabeled curve endpoints cannot establish a year.
        for _, anchor_y, _ in full_years:
            row = sorted((x, value) for x, y, value in full_years if abs(y - anchor_y) <= 12)
            values = [value for _, value in row]
            if len(values) >= 2 and all(a < b for a, b in zip(values, values[1:])):
                return values[-1]
    centuries = {year // 100 for year in context_years if 2000 <= year <= 2099}
    if centuries != {20}:
        return None
    for _, anchor_y, _ in numeric_rows:
        row = sorted((x, values) for x, y, values in numeric_rows if abs(y - anchor_y) <= 12)
        # A sequence such as 04,06,...,26 is sufficient only when the source
        # page also explicitly identifies the century. Month-only legends
        # still retain month precision and never acquire an invented day.
        values = [value for _, group in row for value in group]
        for start in range(len(values) - 3):
            stop = start + 1
            while stop < len(values) and 0 <= values[stop] <= 99 and values[stop] - values[stop - 1] == 2:
                stop += 1
            if stop - start >= 4 and 0 <= values[start] <= 99:
                return 2000 + values[stop - 1]
    return None


def _observation(raw: str, axis_year: int | None, today: date) -> tuple[str | None, str | None]:
    raw = raw.strip()
    if raw.casefold() == "final":
        return None, None
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", raw)
    if match:
        month, day, year = (int(value) for value in match.groups())
        year = 2000 + year if year < 100 else year
        observed = date(year, month, day)
        if observed > today:
            raise ValueError("future-dated observation rejected")
        return observed.isoformat(), observed.strftime("%Y-%m")
    match = re.fullmatch(r"([A-Za-z]{3})\s*(\d{1,2})?(?:\s*,?\s*(\d{4}))?", raw)
    if not match or match[1].title() not in MONTHS:
        raise ValueError("unrecognized legend date")
    month = MONTHS[match[1].title()]
    year = int(match[3]) if match[3] else axis_year
    if year is None:
        # Do not stamp a capture date onto a legend with an unknown year.
        raise ValueError("legend observation year is unknown")
    if match[2]:
        observed = date(year, month, int(match[2]))
        if observed > today:
            raise ValueError("future-dated observation rejected")
        return observed.isoformat(), observed.strftime("%Y-%m")
    if (year, month) > (today.year, today.month):
        raise ValueError("future-dated observation month rejected")
    return None, f"{year:04}-{month:02}"


_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_LEGEND = re.compile(rf"^\s*(?P<label>.*?)\s*\((?P<date>[^()=]+)\s*=\s*(?P<value>{_NUMBER})\s*\)\s*$")


def _metric_identity(chart_id: str, label: str) -> tuple[str, str, str, str] | None:
    normalized = re.sub(r"\s+", " ", label.replace("*", "").strip()).casefold()
    compact = re.sub(r"\s+", "", normalized).strip("—_-")
    # OCR may read the colored line or histogram sample as punctuation. Only
    # discard that prefix; do not repair digits, dates, or metric labels.
    if chart_id == "mega7_shares":
        match = re.fullmatch(r"mag-7shareofs&p500(capitalization|forwardearnings|forwardrevenues)", compact)
        if match:
            kind = {"capitalization": "market_cap", "forwardearnings": "forward_earnings", "forwardrevenues": "forward_revenues"}[match[1]]
            return f"mega7_{kind}_share", "mega7", "percent", "forward_12m" if kind != "market_cap" else "current"
    elif chart_id == "sector_neri":
        for text, subject in SECTORS.items():
            # I/l ambiguity is confined to the known NERI label, never values.
            if re.fullmatch(rf"[li|!]*{re.escape(text.replace(' ', ''))}ner[il]", compact):
                return "sector_neri", subject, "percent", "rolling_3m"
    elif chart_id == "sp500_eps":
        if compact == "consensusforwardeps":
            return "forward_eps", "sp500", "USD_per_share", "forward_12m"
        match = re.fullmatch(r"consensus(20\d{2})eps", compact)
        if match:
            return f"annual_eps:{match[1]}", "sp500", "USD_per_share", match[1]
    elif chart_id == "group_forward_earnings":
        groups = {
            "s&p500": "sp500",
            "s&p493": "sp493",
            "s&p500ex-magnificent-7": "sp493",
            "magnificent-7": "mega7",
        }
        if compact in groups:
            return "forward_total_earnings", groups[compact], "USD_billions", "forward_12m"
    return None


def parse_chart(
    chart_id: str,
    items: Iterable,
    *,
    now: datetime,
    reference_id: str,
    locator: str,
    context_years: set[int] | None = None,
) -> tuple[list[dict], list[str]]:
    """Parse injectable OCR detections; ambiguous/missing values stay missing."""
    lines = _lines(items)
    axis_year = _axis_year(lines, context_years=context_years or set())
    metrics: dict[tuple[str, str], dict] = {}
    duplicates: set[tuple[str, str]] = set()
    errors = []
    for line in _joined_lines(lines):
        # Recognition occasionally emits a full-width parenthesis. Normalize
        # typography only; numeric characters and dates are never repaired.
        syntax = line.text.translate(str.maketrans({"（": "(", "）": ")", "＝": "="}))
        match = _LEGEND.fullmatch(syntax)
        if not match:
            continue
        identity = _metric_identity(chart_id, match["label"])
        if identity is None:
            continue
        metric_id, subject, unit, target = identity
        try:
            value = float(match["value"].replace(",", ""))
            minimum, maximum = (
                (-100, 100)
                if metric_id == "sector_neri"
                else (0, 100)
                if unit == "percent"
                else (0, 100_000)
                if unit == "USD_billions"
                else (0, 5000)
            )
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError("legend value outside metric range")
            observation_date, observation_period = _observation(match["date"], axis_year, now.date())
            if match["date"].strip().casefold() == "final" and not metric_id.startswith("annual_eps:"):
                raise ValueError("Final only applies to fixed-calendar annual EPS")
        except ValueError as exc:
            errors.append(f"{metric_id}/{subject}: {exc}")
            continue
        key = metric_id, subject
        metric = {
            "metric_id": metric_id,
            "subject_id": subject,
            "label": match["label"].strip(" —-*"),
            "value": value,
            "unit": unit,
            "target_period": target,
            "observation_date": observation_date,
            "observation_period": observation_period,
            "reference_id": reference_id,
            "locator": locator + "; printed legend: " + line.text,
            "ocr_confidence": line.confidence,
            "date_precision": "day" if observation_date else "month" if observation_period else "unknown",
        }
        if metric_id == "sector_neri":
            metric["definition"] = "3-month moving average of estimates up minus estimates down, as percent of total estimates"
        if metric_id == "forward_eps":
            metric["definition"] = "time-weighted consensus EPS for the current and coming calendar year"
        if metric_id == "forward_total_earnings":
            metric["definition"] = "aggregate forward consensus operating earnings in billion dollars; not earnings per share"
        if metric_id.startswith("annual_eps:"):
            metric["estimate_status"] = "final" if match["date"].strip().casefold() == "final" else "forecast"
        if key in metrics:
            duplicates.add(key)
        metrics[key] = metric
    for key in duplicates:
        metrics.pop(key, None)
        errors.append(f"{key[0]}/{key[1]}: ambiguous duplicate legend")
    if chart_id == "mega7_shares" and len({metric["observation_date"] for metric in metrics.values()}) > 1:
        # These are the three series in one weekly shares chart. Inconsistent
        # legend dates cannot become a single concentration observation.
        errors.append("share legends have inconsistent observation dates")
        metrics.clear()
    return list(metrics.values()), errors


def fetch_yardeni(
    capture_dir: Path,
    now: datetime,
    *,
    fetcher: Callable[[str], bytes | tuple[bytes, str]] | None = None,
    ocr: Callable[[bytes], Iterable] | None = None,
) -> dict:
    """Fetch fresh pages/images, save content-addressed evidence, return metrics.

    ``fetcher(url)`` may return bytes or ``(bytes, content_type)``. ``ocr(bytes)``
    returns RapidOCR ``[box, text, confidence]`` rows (or ``OCRLine`` objects).
    Neither dependency is called by deterministic unit tests unless injected.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("retrieval time must be timezone aware")
    now = now.astimezone(timezone.utc)
    capture_dir = Path(capture_dir)
    capture_dir.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or _fetch
    ocr = ocr or _ocr
    result = {
        "source_id": "yardeni",
        "status": "SOURCE_ERROR",
        "retrieved_at": now.isoformat(),
        "publication_date": None,
        "source_url": MAG7_URL,
        "document_id": None,
        "metrics": [],
        "errors": [],
        "captures": [],
    }
    captured: dict[str, tuple[bytes, str]] = {}

    def capture(url: str, *, image: bool = False) -> tuple[bytes, str]:
        if not _allowed_url(url, image=image):
            raise ValueError("unexpected chart source URL")
        if url in captured:
            return captured[url]
        response = fetcher(url)
        payload, content_type = response if isinstance(response, tuple) else (response, "")
        if not isinstance(payload, bytes) or not payload or len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("empty, invalid, or oversized source response")
        if image:
            if payload.startswith(b"\x89PNG\r\n\x1a\n"):
                suffix, content_type = ".png", "image/png"
            elif payload.startswith(b"\xff\xd8\xff"):
                suffix, content_type = ".jpg", "image/jpeg"
            else:
                raise ValueError("chart response is not a PNG or JPEG")
        else:
            suffix, content_type = ".html", content_type or "text/html"
        digest = sha256(payload).hexdigest()
        filename = f"yardeni-{digest}{suffix}"
        path = capture_dir / filename
        if not path.exists():
            path.write_bytes(payload)
        result["captures"].append({"sha256": digest, "relative_path": filename, "url": url, "content_type": content_type})
        captured[url] = payload, digest
        return payload, digest

    for spec in CHARTS:
        try:
            page, _ = capture(spec.page_url)
            charts = _chart_metadata(page)
            if len(charts) < spec.figure:
                raise ValueError("expected figure is missing")
            chart = charts[spec.figure - 1]
            title = str(chart.get("title", "")).upper()
            if not all(term in title for term in spec.title_terms):
                raise ValueError("expected figure identity changed")
            if spec.chart_id == "group_forward_earnings" and "billion dollars" not in str(chart.get("subtitle", "")).lower():
                raise ValueError("aggregate forward earnings unit changed")
            image_url = chart.get("imageUrl")
            if not isinstance(image_url, str):
                raise ValueError("figure has no image URL")
            image, digest = capture(image_url, image=True)
            context_years = {
                int(value)
                for item in charts
                for value in re.findall(r"\b20\d{2}\b", str(item.get("subtitle", "")))
            }
            metrics, errors = parse_chart(
                spec.chart_id,
                ocr(image),
                now=now,
                reference_id="REF-YARDENI-" + spec.chart_id.upper().replace("_", "-") + "-" + digest[:16],
                locator=f"{spec.page_url} — Figure {spec.figure} — {image_url}",
                context_years=context_years,
            )
            result["metrics"].extend(metrics)
            result["errors"].extend(f"{spec.chart_id}: {error}" for error in errors)
            if len(metrics) < spec.expected_metrics:
                result["errors"].append(f"{spec.chart_id}: extracted {len(metrics)}/{spec.expected_metrics} expected printed legend values; unreadable or unverified values omitted")
        except Exception as exc:
            result["errors"].append(f"{spec.chart_id}: {type(exc).__name__}: {exc}")
    if result["captures"]:
        result["document_id"] = sha256(json.dumps([(item["url"], item["sha256"]) for item in result["captures"]], separators=(",", ":")).encode()).hexdigest()
    if result["metrics"]:
        result["status"] = "PARTIAL" if result["errors"] else "AVAILABLE"
    return result
