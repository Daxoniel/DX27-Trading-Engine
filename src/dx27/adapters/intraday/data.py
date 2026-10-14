"""One-minute CSV and historical Alpaca SIP inputs, without broker operations."""

import csv
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.market_data import validate_bar


CSV_FIELDS = ("symbol", "timestamp", "open", "high", "low", "close", "volume")


def aware_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include an explicit UTC offset")
    result = result.astimezone(timezone.utc)
    if result.second or result.microsecond:
        raise ValueError("minute bars must be aligned to a whole minute")
    return result




@dataclass(frozen=True)
class IntradayDataset:
    bars: tuple[MarketContext, ...]
    provenance: dict


def load_csv(path: str | Path) -> IntradayDataset:
    path = Path(path)
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not set(CSV_FIELDS).issubset(reader.fieldnames or ()):
        raise ValueError("CSV requires: " + ",".join(CSV_FIELDS))
    bars, seen = [], set()
    for line, row in enumerate(reader, start=2):
        try:
            bar = MarketContext(row["symbol"].strip().upper(), aware_time(row["timestamp"]), "1m",
                                *(float(row[field]) for field in CSV_FIELDS[2:]))
            validate_bar(bar)
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                raise ValueError("duplicate symbol/timestamp")
            seen.add(key)
            bars.append(bar)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid CSV row {line}: {exc}") from None
    if not bars:
        raise ValueError("CSV contains no bars")
    digest = hashlib.sha256(raw).hexdigest()
    metadata = path.with_suffix(path.suffix + ".metadata.json")
    provenance = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {"source": "LOCAL_CSV_UNVERIFIED"}
    if not isinstance(provenance, dict):
        raise ValueError("source metadata must be a JSON object")
    if "csv_sha256" in provenance and provenance["csv_sha256"] != digest:
        raise ValueError("CSV hash does not match its source metadata")
    if "raw_sha256" in provenance:
        archive = path.with_suffix(path.suffix + ".raw.jsonl")
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != provenance["raw_sha256"]:
            raise ValueError("response archive is missing or does not match its source metadata")
    provenance = dict(provenance, csv_sha256=digest, bar_label="interval_start",
                      decision_availability="ASSUMED_AT_BAR_END_NOT_ORIGINAL_CUTOFF",
                      original_cutoff_verified=False)
    return IntradayDataset(tuple(sorted(bars, key=lambda b: (b.timestamp, b.symbol))), provenance)


def _get_page(url: str, key: str, secret: str) -> bytes:
    request = Request(url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    try:
        with urlopen(request, timeout=45) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Alpaca historical data request failed: HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Alpaca historical data connection failed") from None


def download_alpaca(symbols, start, end, output, *, now=None) -> dict:
    """Download old SIP bars explicitly; never silently fall back to IEX.

    Credentials are read from environment configuration and never saved.
    Raw responses and normalized CSV are sealed by the completion metadata.
    """
    now = now or datetime.now(timezone.utc)
    if start.tzinfo is None or end.tzinfo is None or now.tzinfo is None or end <= start:
        raise ValueError("start/end require offsets and an increasing interval")
    if end > now - timedelta(minutes=15):
        raise ValueError("free historical SIP end must be at least 15 minutes old")
    symbols = sorted(set(s.strip().upper() for s in symbols))
    if not symbols or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9./-]*", s) for s in symbols):
        raise ValueError("provide valid stock/ETF symbols")
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("configure APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment")
    output = Path(output)
    raw_path = output.with_suffix(output.suffix + ".raw.jsonl")
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    if any(p.exists() for p in (output, raw_path, metadata_path)):
        raise FileExistsError("download outputs already exist; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    buffer, raw_pages, response_hashes, tokens = io.StringIO(), [], [], set()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    token, rows = None, 0
    started = datetime.now(timezone.utc).isoformat()
    while True:
        query = dict(symbols=",".join(symbols), timeframe="1Min", start=start.isoformat(),
                     end=end.isoformat(), feed="sip", adjustment="raw", sort="asc", limit=10_000)
        if token:
            query["page_token"] = token
        raw = _get_page("https://data.alpaca.markets/v2/stocks/bars?" + urlencode(query), key, secret)
        page = json.loads(raw)
        if not isinstance(page.get("bars"), dict):
            raise RuntimeError("Alpaca returned an unexpected bar schema")
        raw_pages.append(json.dumps(page, separators=(",", ":"), sort_keys=True))
        response_hashes.append(hashlib.sha256(raw).hexdigest())
        for symbol, values in page["bars"].items():
            if symbol not in symbols:
                raise RuntimeError("Alpaca returned an unrequested symbol")
            for value in values:
                timestamp = aware_time(value["t"])
                if timestamp == end:
                    continue  # Normalize an inclusive provider end to our exclusive end.
                if not start <= timestamp < end:
                    raise RuntimeError("Alpaca returned a bar outside the requested interval")
                bar = MarketContext(symbol, timestamp, "1m", *(float(value[k]) for k in ("o", "h", "l", "c", "v")))
                validate_bar(bar)
                writer.writerow(dict(zip(CSV_FIELDS, (symbol, timestamp.isoformat(), bar.open, bar.high,
                                                       bar.low, bar.close, bar.volume))))
                rows += 1
        token = page.get("next_page_token")
        if not token:
            break
        if token in tokens:
            raise RuntimeError("Alpaca repeated a pagination token")
        tokens.add(token)
    if not rows:
        raise RuntimeError("Alpaca returned no bars; no successful dataset was written")
    csv_bytes = buffer.getvalue().encode()
    raw_bytes = ("\n".join(raw_pages) + "\n").encode()
    metadata = dict(source="ALPACA_HISTORICAL_SIP", feed="sip", adjustment="raw", symbols=symbols,
                    start=start.isoformat(), end_exclusive=end.isoformat(), rows=rows,
                    retrieved_started_at=started, retrieved_completed_at=datetime.now(timezone.utc).isoformat(),
                    csv_sha256=hashlib.sha256(csv_bytes).hexdigest(), raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    response_sha256=response_hashes, archive_encoding="CANONICAL_JSON_LINES_RESPONSE_OBJECTS",
                    bar_label="interval_start", original_cutoff_verified=False)
    created = []
    try:
        for path, content in ((raw_path, raw_bytes), (output, csv_bytes),
                              (metadata_path, (json.dumps(metadata, indent=2) + "\n").encode())):
            with path.open("xb") as file:
                created.append(path)
                file.write(content)
        load_csv(output)  # Validate duplicates and the seal before claiming success.
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return metadata
