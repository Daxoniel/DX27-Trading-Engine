"""Offline consistency guards for a separately published research registration.

Publication receipts are workflow evidence, not authenticated by this module.
No network requests, registration creation, download, or broker permission.
"""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.intraday.paired_comparison import runtime
from dx27.domains.intraday.market_data import validate_bar

DESIGN_PATH = "docs/research/orb-literature/evaluation-design.json"
DESIGN_SHA256 = "6569c2bf1be38b157132ef4508ade1c88cfe104e96dc7939d38348e16fb27d7d"
CONTRACT = "ORB_FIXED_EVALUATION:1"


def instant(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    return t.astimezone(timezone.utc)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError("DUPLICATE_JSON_KEY")
            out[k] = v
        return out
    def invalid(_):
        raise ValueError("NONFINITE_JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def source_catalogue(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted((root/"src/dx27").rglob("*.py"))}


def load_registration(path, expected_sha256, receipt, *, stage, root=None, a_report_path=None, exposure_audit_path=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    raw = Path(path).read_bytes()
    if len(raw) > 262144 or digest(raw) != expected_sha256:
        raise ValueError("REGISTRATION_HASH_MISMATCH")
    reg = _json(raw)
    if not isinstance(reg, dict):
        raise ValueError("REGISTRATION_OBJECT_REQUIRED")
    design_raw = (root/DESIGN_PATH).read_bytes()
    if digest(design_raw) != DESIGN_SHA256:
        raise ValueError("DESIGN_CHANGED")
    design = _json(design_raw)
    if (reg.get("contract") != CONTRACT or reg.get("status") != "REGISTERED_OFFLINE_RESEARCH"
            or reg.get("evaluation_registered") is not True or reg.get("execution_enabled") is not False
            or stage not in ("A", "B") or reg.get("stage") != stage
            or reg.get("design_sha256") != DESIGN_SHA256):
        raise ValueError("NOT_A_REGISTERED_EVALUATION")
    if reg.get("source_files") != source_catalogue(root):
        raise ValueError("REGISTERED_SOURCE_CHANGED")
    if reg.get("runtime") != runtime():
        raise ValueError("REGISTERED_RUNTIME_CHANGED")
    if reg.get("calendar_versions") != {k: stage_calendar(design, k)[0].calendar_version for k in ("A", "B")}:
        raise ValueError("REGISTERED_CALENDAR_CHANGED")
    if (not isinstance(receipt, dict) or receipt.get("registration_sha256") != expected_sha256
            or not re.fullmatch(r"[0-9a-f]{40}", receipt.get("public_commit", ""))):
        raise ValueError("PUBLICATION_RECEIPT_REQUIRED")
    registered, published = instant(reg["registered_at"]), instant(receipt["published_at"])
    if not instant(design["created_at"]) <= registered <= published <= datetime.now(timezone.utc):
        raise ValueError("REGISTRATION_CHRONOLOGY")
    check = reg.get("exposure_recheck", {})
    if (check.get("result") != "NO_ADDITIONAL_EXPOSURE_RECORDED"
            or not re.fullmatch(r"[0-9a-f]{64}", check.get("audit_sha256", ""))
            or not instant(design["created_at"]) <= instant(check["checked_at"]) <= registered):
        raise ValueError("EXPOSURE_RECHECK_REQUIRED")
    if exposure_audit_path is None:
        raise ValueError("EXPOSURE_AUDIT_FILE_REQUIRED")
    audit_raw = Path(exposure_audit_path).read_bytes()
    if digest(audit_raw) != check["audit_sha256"]:
        raise ValueError("EXPOSURE_AUDIT_SEAL_MISMATCH")
    audit = _json(audit_raw)
    if (not instant(design["created_at"]) <= instant(audit["generated_at"]) <= instant(check["checked_at"])
            or audit.get("stage_exposure", {}).get(stage) != "NO_ADDITIONAL_EXPOSURE_RECORDED"):
        raise ValueError("EXPOSURE_AUDIT_STAGE_MISMATCH")
    gate = published
    if stage == "B":
        if a_report_path is None:
            raise ValueError("A_REPORT_REQUIRED_BEFORE_B")
        a_raw = Path(a_report_path).read_bytes()
        evidence = receipt.get("stage_A_report", {})
        if (digest(a_raw) != evidence.get("sha256")
                or not re.fullmatch(r"[0-9a-f]{40}", evidence.get("public_commit", ""))):
            raise ValueError("A_REPORT_SEAL_MISMATCH")
        a = _json(a_raw)
        if (a.get("status") != "COMPLETE_REGISTERED_HISTORICAL_ANALYSIS" or a.get("stage") != "A"
                or a.get("execution_enabled") is not False or a.get("evaluation_registered") is not True
                or a.get("design_sha256") != DESIGN_SHA256 or a.get("integrity_complete") is not True
                or a.get("source_files") != reg["source_files"] or a.get("runtime") != reg["runtime"]):
            raise ValueError("A_REPORT_INCOMPLETE_OR_RULES_CHANGED")
        if not instant(a["analysis_completed_at"]) <= instant(evidence["published_at"]) <= datetime.now(timezone.utc):
            raise ValueError("A_REPORT_PUBLICATION_IN_FUTURE")
        gate = max(gate, instant(evidence["published_at"]))
    return reg, design, dict(publication_gate=gate, receipt=receipt, registration_sha256=expected_sha256)


def stage_calendar(design, stage):
    spec = design["stages"][stage]
    start = date.fromisoformat(spec["warmup"]["start_session_inclusive"])
    end = date.fromisoformat(spec["evaluation"]["end_session_exclusive"])-timedelta(days=1)
    calendar = load_xnys_calendar(start, end)
    if calendar.source_version != design["data"].get("calendar", {}).get("version", calendar.source_version):
        raise ValueError("DESIGN_CALENDAR_VERSION_MISMATCH")
    sessions = calendar.sessions
    evaluation = tuple(s for s in sessions if spec["evaluation"]["start_session_inclusive"] <= s.session_id)
    minutes = sum(int((s.closes_at-s.opens_at).total_seconds()/60) for s in sessions)
    if (len(sessions) != spec["expected_context_sessions"] or len(evaluation) != spec["evaluation"]["expected_sessions"]
            or minutes != spec["expected_context_regular_minutes"]):
        raise ValueError("DESIGN_CALENDAR_COUNT_MISMATCH")
    return calendar, sessions, evaluation


def validate_dataset(dataset, design, stage, gate, *, now=None):
    """CSV/archive hashes must already have been verified by load_csv in runner."""
    data, spec, meta = design["data"], design["stages"][stage], dataset.provenance
    for k in ("source", "feed", "adjustment", "bar_label"):
        if meta.get(k) != data[k]:
            raise ValueError("DATA_SOURCE_MISMATCH")
    if (meta.get("symbols") != data["symbols"]
            or instant(meta["start"]) != instant(spec["request_start"])
            or instant(meta["end_exclusive"]) != instant(spec["request_end_exclusive"])):
        raise ValueError("DATA_REQUEST_MISMATCH")
    if any(not re.fullmatch(r"[0-9a-f]{64}", meta.get(k, "")) for k in ("csv_sha256", "raw_sha256")):
        raise ValueError("SOURCE_ARCHIVE_SEALS_REQUIRED")
    began, ended = instant(meta["retrieved_started_at"]), instant(meta["retrieved_completed_at"])
    if not gate["publication_gate"] < began <= ended <= (now or datetime.now(timezone.utc)):
        raise ValueError("CAPTURE_BEFORE_PUBLICATION_OR_FUTURE")
    calendar, sessions, evaluation = stage_calendar(design, stage)
    by_day = {s.session_id: s for s in sessions}
    counts = {(s.session_id, symbol): 0 for s in sessions for symbol in data["symbols"]}
    seen = set()
    start, end = instant(spec["request_start"]), instant(spec["request_end_exclusive"])
    for bar in dataset.bars:
        validate_bar(bar)
        if bar.symbol not in data["symbols"] or not start <= bar.timestamp < end:
            raise ValueError("BAR_OUTSIDE_REGISTERED_INPUT")
        key = (bar.symbol, bar.timestamp)
        if key in seen:
            raise ValueError("DUPLICATE_INPUT_BAR")
        seen.add(key)
        local_day = bar.timestamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        session = by_day.get(local_day)
        if session and session.opens_at <= bar.timestamp < session.closes_at:
            if bar.volume <= 0:
                raise ValueError("ZERO_VOLUME_REGULAR_MINUTE")
            counts[(local_day, bar.symbol)] += 1
    if type(meta.get("rows")) is not int or meta["rows"] != len(dataset.bars):
        raise ValueError("SOURCE_ROW_COUNT_MISMATCH")
    if any(counts[(s.session_id, symbol)] != int((s.closes_at-s.opens_at).total_seconds()/60)
           for s in sessions for symbol in data["symbols"]):
        raise ValueError("INCOMPLETE_REGISTERED_CALENDAR")
    return calendar, sessions, evaluation
