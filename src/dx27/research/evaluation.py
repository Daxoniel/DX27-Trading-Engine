"""Guarded local evaluation API; no downloader, CLI, broker, or auto-registration."""

from datetime import date, datetime, timezone

from dx27.adapters.intraday.data import load_csv
from dx27.application.intraday_replay import IntradayLedgerReplay, replay_sessions
from dx27.core.models.execution_costs import ExecutionCosts
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.research.multisession import OpeningDirectionSequence
from dx27.research.opening_direction import MINUTE, NY
from dx27.research.registration import load_registration, validate_dataset, DESIGN_SHA256
from dx27.research.statistics import comparison_report


def _evaluate(dataset, context_sessions, evaluation_sessions, config):
    sequences = {p: OpeningDirectionSequence(evaluation_sessions, p) for p in ("R0", "R1")}
    bars = {b.timestamp: b for b in dataset.bars if b.symbol == "QQQ"}
    for session in evaluation_sessions:
        for i in range(int((session.closes_at-session.opens_at)/MINUTE)):
            at = session.opens_at + i*MINUTE
            for model in sequences.values():
                if model.next_at is not None:
                    model.on_closed_minute(at, bars.get(at), as_of=at+MINUTE)
    results = {p: model.result() for p, model in sequences.items()}
    baseline = IntradayLedgerReplay(config).run(dataset)
    if [d["session"] for d in baseline.daily] != [s.session_id for s in context_sessions]:
        raise ValueError("BASELINE_CONTEXT_CALENDAR_MISMATCH")
    evaluation_ids = {s.session_id for s in evaluation_sessions}
    # Baseline warmup is diagnostic only; no warmup trades may be silently removed.
    for t in baseline.trades:
        t["session"] = datetime.fromisoformat(t["entry_time"]).astimezone(NY).date().isoformat()
        if datetime.fromisoformat(t["exit_time"]).astimezone(NY).date().isoformat() != t["session"]:
            raise ValueError("BASELINE_OVERNIGHT_TRADE")
    if any(f["session"] not in evaluation_ids for f in baseline.trades):
        raise ValueError("BASELINE_WARMUP_TRADE")
    baseline.daily = [d for d in baseline.daily if d["session"] in evaluation_ids]
    baseline.equity = [r for r in baseline.equity if r["session"] in evaluation_ids]
    baseline.quality = [r for r in baseline.quality if r["session"] in evaluation_ids]
    results["baseline"] = baseline
    try:
        report = comparison_report(results, evaluation_sessions)
    except ValueError as exc:
        report = dict(status="BLOCKED_OFFLINE_ANALYSIS", block_reason=str(exc),
                      effectiveness="NOT_EVALUATED", execution_enabled=False,
                      evaluation_registered=False, primary_R1_net_return=None,
                      integrity_complete=False)
    return report, results


def evaluate_synthetic(dataset, *, decision_start=None):
    """Explicit test seam. Never admits a file tagged as real historical data."""
    if dataset.provenance.get("source") != "SYNTHETIC_DEMO":
        raise ValueError("SYNTHETIC_INPUT_REQUIRED")
    _, context = replay_sessions(dataset)
    start = decision_start or context[0].session_id
    evaluation = tuple(s for s in context if s.session_id >= start)
    if not evaluation:
        raise ValueError("EMPTY_EVALUATION")
    config = IntradayReplayConfig(decision_start=date.fromisoformat(start))
    report, results = _evaluate(dataset, context, evaluation, config)
    complete = report["status"] == "COMPLETE_OFFLINE_ARITHMETIC"
    report.update(status="COMPLETE_SYNTHETIC_EVALUATION" if complete else "BLOCKED_SYNTHETIC_EVALUATION",
                  input_source="SYNTHETIC_DEMO")
    return report, results


def run_registered(registration_path, expected_sha256, receipt, input_path, *, stage,
                   exposure_audit_path, a_report_path=None, root=None):
    """Validate registration BEFORE opening new quote CSV; then require full source seals.

    Caller must independently verify publication receipts and data entitlement.
    This API returns artifacts; it never publishes, downloads or places orders.
    """
    reg, design, gate = load_registration(registration_path, expected_sha256, receipt,
        stage=stage, root=root, a_report_path=a_report_path, exposure_audit_path=exposure_audit_path)
    dataset = load_csv(input_path)  # verifies actual CSV and response archive byte hashes
    calendar, context, evaluation = validate_dataset(dataset, design, stage, gate)
    values = dict(design["baseline_config_template"])
    values["decision_start"] = date.fromisoformat(evaluation[0].session_id)
    values["costs"] = ExecutionCosts(**values["costs"])
    config = IntradayReplayConfig(**values)
    report, results = _evaluate(dataset, context, evaluation, config)
    complete = report["status"] == "COMPLETE_OFFLINE_ARITHMETIC"
    report.update(status="COMPLETE_REGISTERED_HISTORICAL_ANALYSIS" if complete else
                  "BLOCKED_REGISTERED_HISTORICAL_ANALYSIS", stage=stage,
                  evaluation_registered=True, effectiveness="NOT_ESTABLISHED",
                  integrity_complete=complete, design_sha256=DESIGN_SHA256,
                  source_files=reg["source_files"], runtime=reg["runtime"],
                  registration_sha256=expected_sha256, publication_receipt=receipt,
                  input=dataset.provenance, calendar_version=calendar.calendar_version,
                  analysis_completed_at=datetime.now(timezone.utc).isoformat())
    for result in results.values():
        result.summary.update(evaluation_registered=True, performance_admissible=complete)
    return report, results


def write_local_artifacts(report, results, output_path):
    """Exclusive local JSON artifacts. Completion seal is written last.

    No atomic whole-directory transaction or automatic cleanup/retry is claimed.
    A failure leaves an inspectable directory without a completion marker.
    """
    import hashlib
    import json
    import os
    from datetime import datetime
    from pathlib import Path

    if (report.get("status") not in ("COMPLETE_SYNTHETIC_EVALUATION", "COMPLETE_REGISTERED_HISTORICAL_ANALYSIS",
                                             "BLOCKED_SYNTHETIC_EVALUATION", "BLOCKED_REGISTERED_HISTORICAL_ANALYSIS")
            or report.get("execution_enabled") is not False or set(results) != {"R0", "R1", "baseline"}):
        raise ValueError("OFFLINE_REPORT_REQUIRED")
    output = Path(output_path)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    hashes = {}
    def default(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError("unsupported artifact type")
    def write(name, value):
        raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=default)+"\n").encode()
        with os.fdopen(os.open(output/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    for profile, result in results.items():
        for kind in ("summary", "daily", "fills", "trades", "equity", "decisions", "quality"):
            write(f"{profile}-{kind}.json", getattr(result, kind))
    write("report.json", report)
    write("completion.json", dict(status="LOCAL_ARTIFACTS_COMPLETE", study_status=report["status"], execution_enabled=False,
                                  artifact_sha256=dict(hashes)))
    return output
