"""Provider profiles and raw-source parsing; temporal policy stays explicit."""

from datetime import date, datetime, timedelta, timezone
import csv
import io
import json
import math
import re
from zoneinfo import ZoneInfo

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow, SubjectRef
from dx27.intelligence.sentinel.sensor_contracts import FeedBinding
from dx27.intelligence.sentinel.sensor_inputs import (
    normalize_series_point,
    AvailabilityStamp,
)

ETF_IDS = (
    "spy",
    "rsp",
    "qqq",
    "iwm",
    "xlk",
    "xlf",
    "xle",
    "xlv",
    "xli",
    "xlp",
    "xly",
    "xlu",
    "xlb",
)
FRED_IDS = {
    "hy_oas": "BAMLH0A0HYM2",
    "ust_2y": "DGS2",
    "ust_10y": "DGS10",
    "sofr": "SOFR",
    "effr": "EFFR",
}
CORE = ("spy", "rsp", "qqq", "iwm", "vix", "hy_oas", "ust_2y", "ust_10y")
NY = ZoneInfo("America/New_York")


def reference_ids(feed):
    if feed in ETF_IDS:
        return ("REF-YAHOO-ADJUSTMENT-IMPLEMENTATION",)
    if feed == "vix":
        return ("REF-CBOE-VIX-DAILY-CAPTURE",)
    if feed == "sofr":
        return ("REF-FRED-CAPTURE-UNITS", "REF-NYFED-SOFR-PUBLICATION")
    return ("REF-FRED-CAPTURE-UNITS",)


def source_requests():
    requests = []
    for feed in ETF_IDS:
        requests.append(
            (
                feed,
                "yahoo-chart-v8",
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                + feed.upper()
                + "?range=2y&interval=1d&events=div%2Csplits&includeAdjustedClose=true",
            )
        )
    requests.append(
        (
            "vix",
            "cboe-daily-csv",
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        )
    )
    for feed, series in FRED_IDS.items():
        requests.append(
            (
                feed,
                "fred-public-csv",
                "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series,
            )
        )
        requests.append(
            (
                feed + "_metadata",
                "fred-series-metadata",
                "https://fred.stlouisfed.org/series/" + series,
            )
        )
    return tuple(requests)


def binding_for(feed, record, raw, store, calendar, as_of=None):
    """Validate response identity/unit/date profile before creating a stable binding."""
    seen = datetime.fromisoformat(record["first_seen_at"])
    if record["http_status"] != 200 or record["error"]:
        raise ValueError("unsuccessful source response")
    validation_ids = [record["capture_id"]]
    source = record["source_id"]
    expected = (
        "yahoo-chart-v8"
        if feed in ETF_IDS
        else "cboe-daily-csv" if feed == "vix" else "fred-public-csv"
    )
    if source != expected:
        raise ValueError("source identity mismatch")
    qualifiers = [
        "PUBLICATION_TIME_UNKNOWN",
        "RECORDED_FIRST_SEEN_ONLY",
        "RESEARCH_BINDING_ONLY",
    ]
    if feed in ETF_IDS:
        result = json.loads(raw)["chart"]
        if result.get("error") or len(result.get("result") or []) != 1:
            raise ValueError("invalid Yahoo result")
        meta = result["result"][0]["meta"]
        if (
            meta.get("symbol") != feed.upper()
            or meta.get("currency") != "USD"
            or meta.get("instrumentType") != "ETF"
            or meta.get("exchangeTimezoneName") != "America/New_York"
        ):
            raise ValueError("ETF identity/unit/timezone metadata mismatch")
        raw_unit = unit = "USD"
        kind = "ETF"
        policy = "XNYS_SESSION"
        price_basis = "TOTAL_RETURN_AS_AVAILABLE"
        source_calendar = "XNYS"
        qualifiers.append("ADJUSTED_PRICE_AS_CAPTURED_NOT_HISTORIC_VINTAGE")
    elif feed == "vix":
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != ["DATE", "OPEN", "HIGH", "LOW", "CLOSE"]:
            raise ValueError("Cboe daily VIX schema mismatch")
        raw_unit = unit = "percent_annualized"
        kind = "INDEX_SERIES"
        policy = "LOCAL_DATE_BEFORE_EXCLUSIVE_END"
        price_basis = "NOT_PRICE"
        source_calendar = "US_CALENDAR_DAY"
        qualifiers.append("CONSERVATIVE_FULL_DATE_WINDOW_NO_VERIFIED_CLOSE_CLOCK")
    elif feed in FRED_IDS:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != ["observation_date", FRED_IDS[feed]]:
            raise ValueError("FRED series identity mismatch")
        metadata = [
            r
            for r in store.records()
            if r["feed_id"] == feed + "_metadata"
            and r["http_status"] == 200
            and not r["error"]
            and (as_of is None or datetime.fromisoformat(r["first_seen_at"]) <= as_of)
        ]
        if not metadata:
            raise ValueError("FRED units metadata not captured")
        meta = min(metadata, key=lambda r: r["first_seen_at"])
        html = store.get(meta["capture_id"])[1].decode("utf-8")
        units = re.search(r'class="series-meta-value-units"[^>]*>\s*([^<]+)', html)
        frequency = re.search(
            r'class="series-meta-value-frequency"[^>]*>\s*([^<]+)', html
        )
        if (
            FRED_IDS[feed] not in html
            or not units
            or units.group(1).strip() != "Percent"
            or not frequency
            or not frequency.group(1).strip().startswith("Daily")
        ):
            raise ValueError("FRED unit/frequency metadata mismatch")
        seen = max(seen, datetime.fromisoformat(meta["first_seen_at"]))
        validation_ids.append(meta["capture_id"])
        raw_unit = "percent" if feed == "hy_oas" else "percent_per_annum"
        unit = "basis_points" if feed == "hy_oas" else "percent_per_annum"
        kind = "ECONOMIC_SERIES"
        policy = "LOCAL_DATE_BEFORE_EXCLUSIVE_END"
        price_basis = "NOT_PRICE"
        source_calendar = "US_CALENDAR_DAY"
        qualifiers.append("CONSERVATIVE_FULL_DATE_WINDOW_NO_VERIFIED_CLOSE_CLOCK")
    else:
        raise ValueError("unregistered feed")
    profile = {
        "feed_id": feed,
        "source_id": source,
        "source_version": "recorded-source-profile-v1",
        "unit": unit,
        "raw_unit": raw_unit,
        "label_policy": policy,
        "price_basis": price_basis,
        "source_calendar_id": source_calendar,
        "metadata_scope": "VERIFIED_RESPONSE_IDENTITY_UNITS_AND_CONSERVATIVE_WINDOW_NOT_OPERATING_COVERAGE",
    }
    profile_id = stable_content_hash(profile)
    validation = store.binding_record(
        feed,
        {
            "profile_id": profile_id,
            "profile": profile,
            "validation_capture_id": record["capture_id"],
            "validation_capture_ids": validation_ids,
            "validated_at": seen.isoformat(),
            "qualifiers": qualifiers,
        },
    )
    subject = SubjectRef(
        (
            feed.upper()
            if feed in ETF_IDS
            else ("CBOE:VIX" if feed == "vix" else FRED_IDS[feed])
        ),
        kind,
        symbol=feed.upper() if feed in ETF_IDS else None,
    )
    binding = FeedBinding(
        feed,
        subject,
        source,
        "recorded-source-profile-v1",
        raw_unit,
        unit,
        validation["validation_capture_id"],
        datetime.fromisoformat(validation["validated_at"]),
        source_calendar,
        price_basis,
        observation_label_policy=policy,
        ohlcv_timestamp_policy="SESSION_OPEN",
    )
    return binding, tuple(qualifiers)


def normalize_capture(feed, binding, record, raw, calendar):
    seen = datetime.fromisoformat(record["first_seen_at"])
    points = []
    incomplete = out_of_scope = bad = 0

    def add(day, value, source_fields, status=DataStatus.AVAILABLE):
        nonlocal incomplete, out_of_scope, bad
        if not calendar.valid_from <= day <= calendar.valid_through:
            out_of_scope += 1
            return
        if binding.observation_label_policy == "XNYS_SESSION":
            session = calendar.get(day)
            window = ObservationWindow(session.opens_at, session.closes_at, "1d")
        else:
            start = datetime.fromisoformat(day).replace(tzinfo=NY)
            window = ObservationWindow(start, start + timedelta(days=1), "1d")
        if window.end > seen:
            incomplete += 1
            return
        if status is DataStatus.SOURCE_ERROR:
            bad += 1
        revision = stable_content_hash(
            {"profile": binding.source_version, "row": source_fields}
        )
        stamp = AvailabilityStamp(
            None, seen, feed + ":" + day, revision, record["payload_sha256"]
        )
        points.append(
            normalize_series_point(
                binding,
                window,
                status,
                value if status is DataStatus.AVAILABLE else None,
                stamp,
            )
        )

    if feed in ETF_IDS:
        result = json.loads(raw)["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        adj = result["indicators"]["adjclose"][0]["adjclose"]
        if len(adj) != len(timestamps) or any(
            len(quote[k]) != len(timestamps)
            for k in ("open", "high", "low", "close", "volume")
        ):
            raise ValueError("unmatched Yahoo daily arrays")
        days = set()
        for i, ts in enumerate(timestamps):
            observed = datetime.fromtimestamp(ts, timezone.utc)
            day = observed.astimezone(NY).date().isoformat()
            if day in days:
                raise ValueError("duplicate daily Yahoo observation")
            days.add(day)
            numbers = [
                quote[k][i] for k in ("open", "high", "low", "close", "volume")
            ] + [adj[i]]
            status = DataStatus.AVAILABLE
            if any(
                isinstance(v, bool)
                or not isinstance(v, (float, int))
                or not math.isfinite(v)
                for v in numbers
            ):
                status = DataStatus.SOURCE_ERROR
            elif min(numbers[:4] + [numbers[-1]]) <= 0 or numbers[4] < 0:
                status = DataStatus.SOURCE_ERROR
            elif quote["high"][i] + 1e-12 * max(numbers[:4]) < max(
                quote["open"][i], quote["close"][i], quote["low"][i]
            ) or quote["low"][i] - 1e-12 * max(numbers[:4]) > min(
                quote["open"][i], quote["close"][i], quote["high"][i]
            ):
                status = DataStatus.SOURCE_ERROR
            if (
                calendar.valid_from <= day <= calendar.valid_through
                and observed != calendar.get(day).opens_at
            ):
                status = DataStatus.SOURCE_ERROR
            # Adjusted close is the captured provider chain, never an old release.
            add(day, adj[i], numbers, status)
    else:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        days = set()
        for row in reader:
            day = (
                datetime.strptime(row["DATE"], "%m/%d/%Y").date().isoformat()
                if feed == "vix"
                else row["observation_date"]
            )
            date.fromisoformat(day)
            if day in days:
                raise ValueError("duplicate scalar observation")
            days.add(day)
            text = row["CLOSE"] if feed == "vix" else row[FRED_IDS[feed]]
            status = (
                DataStatus.UNAVAILABLE if text in ("", ".") else DataStatus.AVAILABLE
            )
            value = None
            if status is DataStatus.AVAILABLE:
                try:
                    value = float(text)
                    if not math.isfinite(value) or (
                        feed in ("vix", "hy_oas") and value < 0
                    ):
                        raise ValueError("invalid level")
                except (TypeError, ValueError):
                    status = DataStatus.SOURCE_ERROR
                    value = None
            add(day, value, tuple(sorted(row.items())), status)
    if not points:
        raise ValueError("no complete observations inside configured scope")
    return tuple(points), {
        "normalized_points": len(points),
        "incomplete_observations_excluded": incomplete,
        "out_of_scope_rows": out_of_scope,
        "source_error_rows": bad,
    }
