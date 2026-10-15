"""Sealed INTRA-1C fixed paired historical evaluation; no downloads or orders."""

import argparse
import csv
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
from math import ceil, isclose, isfinite
from pathlib import Path
import sys

import numpy as np

from dx27.adapters.intraday.cli import write_report
from dx27.adapters.intraday.data import aware_time, load_csv
from dx27.application.intraday_replay import IntradayLedgerReplay, replay_sessions
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


def runtime():
    return dict(python=".".join(map(str, sys.version_info[:2])),
                packages={k: importlib.metadata.version(k) for k in ("numpy", "pandas", "exchange-calendars")})


def _instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("NAIVE_RECEIPT_TIMESTAMP")
    return result.astimezone(timezone.utc)


def source_files(root):
    prefixes = ["src/dx27/domains/intraday", "src/dx27/core", "src/dx27/adapters/simulated",
                "src/dx27/adapters/calendars", "src/dx27/execution_planning"]
    files = {p for prefix in prefixes for p in (root / prefix).rglob("*.py")}
    files |= {root / "src/dx27/application/intraday_replay.py", root / "src/dx27/adapters/intraday/data.py"}
    return {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def load_protocol(path, expected_sha256, *, root=None):
    raw = Path(path).read_bytes()
    if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("PROTOCOL_HASH_MISMATCH")
    protocol = json.loads(raw)
    if protocol["contract"] != "INTRA-1C:1" or protocol["execution_enabled"] is not False:
        raise ValueError("INVALID_PROTOCOL")
    root = root or Path(__file__).resolve().parents[4]
    if protocol["engine_files"] != source_files(root):
        raise ValueError("REGISTERED_ENGINE_CHANGED")
    if protocol["runtime"] != runtime():
        raise ValueError("REGISTERED_RUNTIME_CHANGED")
    analysis = protocol["analysis"]
    bootstrap = analysis["bootstrap"]
    if (analysis["primary"] != "RVOL_MINUS_BASELINE_NET_RETURN_PERCENTAGE_POINTS"
            or bootstrap["method"] != "PAIRED_CIRCULAR_MOVING_BLOCK_COMPOUNDED_RETURNS"
            or bootstrap["quantiles"] != [0.025, 0.975] or bootstrap["quantile_method"] != "linear"
            or analysis["zero_trade_days"] != "INCLUDE"
            or analysis["incomplete_data"] != "BLOCK_BOTH_ARMS_NO_SESSION_DROPPING"
            or analysis["parameter_search"] != "NONE" or analysis["alternative_periods"] != "NONE"):
        raise ValueError("UNSUPPORTED_REGISTERED_ANALYSIS")
    if (protocol["baseline_config"].get("opening_volume") is not None
            or protocol["baseline_config"]["decision_start"] != protocol["data"]["evaluation_start"]
            or aware_time(protocol["data"]["end_exclusive"]).date().isoformat() != protocol["data"]["evaluation_end_exclusive"]):
        raise ValueError("INVALID_COMPARISON_BOUNDS")
    return protocol, raw


def validate_dataset(dataset, protocol):
    declared, actual = protocol["data"], dataset.provenance
    for key in ("source", "feed", "adjustment", "bar_label"):
        if actual.get(key) != declared[key]:
            raise ValueError("REGISTERED_SOURCE_MISMATCH")
    if not actual.get("csv_sha256") or not actual.get("raw_sha256"):
        raise ValueError("SEALED_ARCHIVE_REQUIRED")
    start, end = (aware_time(declared[k]) for k in ("start", "end_exclusive"))
    if (aware_time(actual["start"]) != start or aware_time(actual["end_exclusive"]) != end
            or sorted(actual["symbols"]) != declared["symbols"]
            or sorted({b.symbol for b in dataset.bars}) != declared["symbols"]
            or any(not start <= b.timestamp < end for b in dataset.bars)):
        raise ValueError("REGISTERED_DATA_BOUNDS_MISMATCH")
    if _instant(actual["retrieved_started_at"]) <= _instant(protocol["registered_at"]):
        raise ValueError("DATA_RETRIEVAL_PRECEDES_REGISTRATION")
    _, sessions = replay_sessions(dataset)
    evaluation = [s for s in sessions if declared["evaluation_start"] <= s.session_id < declared["evaluation_end_exclusive"]]
    if len(sessions) != declared["expected_context_sessions"] or len(evaluation) != declared["expected_evaluation_sessions"]:
        raise ValueError("REGISTERED_SESSION_COUNT_MISMATCH")


def paired_interval(baseline, rvol, *, block_sessions, resamples, seed, **unused):
    a, b = np.asarray(baseline, dtype=float), np.asarray(rvol, dtype=float)
    if (a.ndim != 1 or a.shape != b.shape or not len(a) or len(a) > 1000
            or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b))
            or np.any(a <= -1) or np.any(b <= -1)
            or type(block_sessions) is not int or not 1 <= block_sessions <= len(a)
            or type(resamples) is not int or not 1 <= resamples <= 100000
            or type(seed) is not int or seed < 0):
        raise ValueError("INVALID_PAIRED_BOOTSTRAP_INPUT")
    rng = np.random.Generator(np.random.PCG64(seed))
    starts = rng.integers(0, len(a), size=(resamples, ceil(len(a) / block_sessions)))
    indices = ((starts[:, :, None] + np.arange(block_sessions)) % len(a)).reshape(resamples, -1)[:, :len(a)]
    deltas = (np.prod(1 + b[indices], axis=1) - np.prod(1 + a[indices], axis=1)) * 100
    if not np.all(np.isfinite(deltas)):
        raise ValueError("NONFINITE_BOOTSTRAP_RESULT")
    return [float(v) for v in np.quantile(deltas, [0.025, 0.975], method="linear")]


def _audit(result, initial_cash):
    residuals = dict(cash_flow=result.summary["ending_cash"] - initial_cash - sum(f["cash_delta"] for f in result.fills),
                     closed_trade_pnl=result.summary["ending_equity"] - initial_cash - sum(t["net_pnl"] for t in result.trades),
                     minute_equity=max((abs(r["cash"] + r["holdings_value"] - r["equity"]) for r in result.equity), default=0))
    if any(not isfinite(v) or abs(v) > 1e-6 for v in residuals.values()):
        raise ValueError("INDEPENDENT_ACCOUNTING_CHECK_FAILED")
    return residuals


def compare_results(baseline, rvol, protocol):
    results = dict(baseline=baseline, rvol=rvol)
    output = dict(task="INTRA-1C", study_id=protocol["study_id"], execution_enabled=False,
                  algorithm_optimization_performed=False, effectiveness="NOT_ESTABLISHED",
                  primary_delta_net_return_pp=None, paired_bootstrap_95_interval_pp=None,
                  arms={key: value.summary for key, value in results.items()}, independent_accounting={},
                  evaluation_sessions=0, status="BLOCKED_INCOMPLETE_COMPARISON")
    if any(r.summary["status"] != "COMPLETE_REPLAY" or r.summary["open_positions"]
           or not r.summary["performance_admissible"] for r in results.values()):
        return output, []
    cfg, spec = protocol["baseline_config"], protocol["data"]
    if (baseline.summary["config"] != cfg
            or rvol.summary["config"] != dict(cfg, opening_volume=protocol["rvol"])
            or baseline.summary["input"]["csv_sha256"] != rvol.summary["input"]["csv_sha256"]
            or baseline.summary["calendar_version"] != rvol.summary["calendar_version"]):
        raise ValueError("PAIRED_CONFIGURATION_OR_SOURCE_MISMATCH")
    initial = cfg["initial_cash"]
    daily = {key: [d for d in result.daily if spec["evaluation_start"] <= d["session"] < spec["evaluation_end_exclusive"]]
             for key, result in results.items()}
    if (len(daily["baseline"]) != spec["expected_evaluation_sessions"]
            or [r["session"] for r in daily["baseline"]] != [r["session"] for r in daily["rvol"]]
            or len({r["session"] for r in daily["baseline"]}) != len(daily["baseline"])):
        raise ValueError("PAIRED_SESSION_MISMATCH")
    for key, result in results.items():
        if any(not d["data_complete"] or d["open_positions"] for d in daily[key]):
            return output, []
        output["independent_accounting"][key] = _audit(result, initial)
        previous = initial
        for d in daily[key]:
            if (not isfinite(d["ending_equity"]) or d["ending_equity"] <= 0
                    or not isclose(d["starting_equity"], previous, rel_tol=0, abs_tol=1e-6)):
                raise ValueError("DAILY_EQUITY_CHAIN_MISMATCH")
            previous = d["ending_equity"]
        if not isclose(previous, result.summary["ending_equity"], rel_tol=0, abs_tol=1e-6):
            raise ValueError("PERIOD_EQUITY_MISMATCH")
    pairs = [dict(session=a["session"], baseline_return=a["ending_equity"] / a["starting_equity"] - 1,
                  rvol_return=b["ending_equity"] / b["starting_equity"] - 1)
             for a, b in zip(daily["baseline"], daily["rvol"])]
    for key, result in results.items():
        output["arms"][key] = dict(result.summary,
            evaluation_net_return=result.summary["net_pnl"] / initial,
            win_rate=sum(t["net_pnl"] > 0 for t in result.trades) / len(result.trades) if result.trades else None)
    output.update(status="COMPLETE_FIXED_HISTORICAL_COMPARISON", evaluation_sessions=len(pairs),
                  primary_delta_net_return_pp=(rvol.summary["net_pnl"] - baseline.summary["net_pnl"]) / initial * 100,
                  paired_bootstrap_95_interval_pp=paired_interval(
                      [r["baseline_return"] for r in pairs], [r["rvol_return"] for r in pairs],
                      **protocol["analysis"]["bootstrap"]))
    return output, pairs


def run_comparison(protocol_path, expected_sha256, input_path, output_path):
    output = Path(output_path)
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    protocol, raw_protocol = load_protocol(protocol_path, expected_sha256)
    dataset = load_csv(input_path)
    validate_dataset(dataset, protocol)
    # Reuse the unchanged strategy engine; only the opt-in selection differs.
    config_values = protocol["baseline_config"]
    from dx27.core.models.execution_costs import ExecutionCosts
    from dx27.domains.intraday.replay_config import IntradayReplayConfig
    cfg = IntradayReplayConfig(**dict(config_values, decision_start=date.fromisoformat(config_values["decision_start"]),
                                     costs=ExecutionCosts(**config_values["costs"])))
    a = IntradayLedgerReplay(cfg).run(dataset)
    b = IntradayLedgerReplay(replace(cfg, opening_volume=OpeningVolumeConfig(**protocol["rvol"]))).run(dataset)
    summary, pairs = compare_results(a, b, protocol)
    summary.update(protocol_sha256=expected_sha256, source_csv_sha256=dataset.provenance["csv_sha256"],
                   source_archive_sha256=dataset.provenance["raw_sha256"], runtime=runtime(),
                   bootstrap=protocol["analysis"]["bootstrap"], registered_at=protocol["registered_at"],
                   retrieved_started_at=dataset.provenance["retrieved_started_at"],
                   original_cutoff_verified=False, prospective_or_blind=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_bytes(raw_protocol)
    write_report(a, output / "baseline")
    write_report(b, output / "rvol")
    (output / "comparison.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (output / "paired-daily.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["session", "baseline_return", "rvol_return"])
        writer.writeheader(); writer.writerows(pairs)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_comparison(args.protocol, args.protocol_sha256, args.input, args.output)
        print(json.dumps({k: result[k] for k in ("status", "primary_delta_net_return_pp", "paired_bootstrap_95_interval_pp", "execution_enabled")}))
        return 0 if result["status"] == "COMPLETE_FIXED_HISTORICAL_COMPARISON" else 2
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, AssertionError):
        print(json.dumps(dict(status="INTRA_1C_FAILED", execution_enabled=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
