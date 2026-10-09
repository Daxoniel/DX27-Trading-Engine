"""Offline frozen synthetic runner: python -m ...change_synthetic --output DIR."""

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import platform
import numpy as np
from dx27.adapters.calendars.xnys import load_xnys_calendar
from .change_inputs import CASES, generate, subjects, snapshots
from .change_detection import replay, METHODS
from .change_scoring import (
    targets,
    session_statistics,
    metrics,
    paired_interval,
    block_indices,
    verdict,
)


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def write_json(path, value):
    path.write_bytes(encoded(value) + b"\n")


def finite_list(x):
    return [float(v) if np.isfinite(v) else None for v in x]


def verify_protocol(root):
    directory = root / "research/sentinel/6b-2j-a-change-protocol"
    protocol = json.loads((directory / "protocol.json").read_bytes())
    lock = json.loads((directory / "protocol_lock.json").read_bytes())
    for name, key in [
        ("protocol.json", "protocol_file_sha256"),
        ("references.json", "references_file_sha256"),
    ]:
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != lock[key]:
            raise ValueError("frozen protocol hash mismatch")
    parent = root / protocol["parent"]["path"]
    if (
        hashlib.sha256(parent.read_bytes()).hexdigest()
        != protocol["parent"]["file_sha256"]
    ):
        raise ValueError("parent hash mismatch")
    if protocol["evaluation"] != json.loads(parent.read_bytes())["evaluation"]:
        raise ValueError("evaluation drift")
    if protocol["production_enabled"] or protocol["confirmation_started"]:
        raise ValueError("synthetic gate violation")
    expected = {
        "minimum_labels_per_target_subject_direction": 30,
        "minimum_precision": 0.6,
        "minimum_recall": 0.6,
        "maximum_median_delay_sessions": 3,
        "maximum_p90_delay_sessions": 5,
        "maximum_unmatched_alarms_per_252_eligible_sessions": 12,
        "minimum_evaluation_availability": 0.95,
        "minimum_absolute_f1_improvement_over_fixed_baseline": 0.05,
        "f1_improvement_95pct_block_interval_lower_bound": 0.0,
        "pooled_results_cannot_override_failed_stratum": True,
    }
    if protocol["evaluation"]["change_gate"] != expected:
        raise ValueError("scorer constants differ from lock")
    return protocol, lock


@contextmanager
def gzip_lines(path):
    # Reproducible bytes, with both the gzip wrapper and underlying file closed.
    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=1
        ) as stream:
            yield stream


def run(root, output):
    p, lock = verify_protocol(root)
    output.mkdir(parents=True, exist_ok=False)
    calendar = load_xnys_calendar(date(2003, 1, 1), date(2027, 12, 31))
    sessions = [s for s in calendar.sessions if s.session_id >= "2005-01-01"][:1200]
    starts = block_indices(1200)
    counts = Counter()
    integrity = Counter({k: 0 for k in p["synthetic_plan"]["correctness_gates"]})
    checked = Counter()
    runs = 0
    diagnostic = []
    for case in CASES:
        with gzip_lines(output / f"{case}-evidence.jsonl.gz") as evidence, gzip_lines(
            output / f"{case}-metrics.jsonl.gz"
        ) as metricfile:
            for split, seeds in p["synthetic_plan"]["seeds"].items():
                for seed in seeds:
                    online, truth, captures = generate(case, seed)
                    rows = subjects(online)
                    outcomes = {
                        "trend:SPY": truth[:, 0],
                        "trend:RSP": truth[:, 1],
                        "volatility:SPY": truth[:, 0],
                        "relationship:RSP/SPY": truth[:, 1] - truth[:, 0],
                        "relationship:QQQ/SPY": truth[:, 2] - truth[:, 0],
                    }
                    evidence.write(
                        encoded(
                            {
                                "type": "inputs",
                                "case": case,
                                "split": split,
                                "seed": seed,
                                "snapshots": [asdict(s) for s in online],
                                "captures": [asdict(c) for c in captures],
                                "evaluation_only_outcomes": {
                                    k: finite_list(v) for k, v in outcomes.items()
                                },
                            }
                        )
                        + b"\n"
                    )
                    if seed in (seeds[0],):
                        original = snapshots(captures, 650)
                        integrity["late_revision_changes_original_snapshot"] += sum(
                            a != b for a, b in zip(original, online[:650])
                        )
                        checked["snapshot_prefix"] += 1
                    for subject, x in rows.items():
                        family = subject.split(":")[0]
                        valid, labels = targets(outcomes[subject], family)
                        streams = {
                            method: replay(x, family, method) for method in METHODS
                        }
                        scored = {}
                        for method, decisions in streams.items():
                            for direction in (-1, 1):
                                stats, delays, matches = session_statistics(
                                    labels, decisions, valid, direction
                                )
                                scored[method, direction] = (
                                    stats,
                                    metrics(stats, delays),
                                    matches,
                                )
                        for method, decisions in streams.items():
                            integrity["warmup_or_gap_violations"] += sum(
                                d.alarm != 0 for d in decisions[:252]
                            )
                            integrity["missing_as_zero_or_participation_mislabel"] += (
                                sum(
                                    d.available or d.alarm != 0
                                    for i, d in enumerate(decisions)
                                    if not np.isfinite(x[i])
                                )
                                if not (
                                    method == "EWMAC_64_256_RESEARCH_ONLY"
                                    and family != "trend"
                                )
                                else 0
                            )
                            for direction in (-1, 1):
                                matches = scored[method, direction][2]
                                integrity["duplicate_one_to_one_matches"] += int(
                                    len({m[0] for m in matches}) != len(matches)
                                    or len({m[1] for m in matches}) != len(matches)
                                )
                            if seed == seeds[0]:
                                prefix = replay(x[:650], family, method)
                                changed = x.copy()
                                changed[650:] += 1
                                altered = replay(changed, family, method)
                                integrity["prefix_replay_mismatches"] += sum(
                                    a != b for a, b in zip(prefix, decisions[:650])
                                )
                                integrity[
                                    "future_perturbation_changes_past_outputs"
                                ] += sum(
                                    a != b
                                    for a, b in zip(altered[:650], decisions[:650])
                                )
                                checked["stream_prefix_and_future"] += 1
                            evidence.write(
                                encoded(
                                    {
                                        "type": "stream",
                                        "seed": seed,
                                        "split": split,
                                        "subject": subject,
                                        "method": method,
                                        "decision_columns": {
                                            key: [getattr(d, key) for d in decisions]
                                            for key in (
                                                "available",
                                                "reason",
                                                "statistic",
                                                "raw_alarm",
                                                "alarm",
                                                "suppressed",
                                                "reset",
                                            )
                                        },
                                        "valid_label_sessions": np.flatnonzero(
                                            valid
                                        ).tolist(),
                                        "targets": labels,
                                        "matches": scored[method, 1][2],
                                    }
                                )
                                + b"\n"
                            )
                            for direction in (-1, 1):
                                stats, m, matches = scored[method, direction]
                                base_stats, base, _ = scored[
                                    "FIXED_CAUSAL_THRESHOLD_V1", direction
                                ]
                                is_candidate = method in METHODS[-2:]
                                uplift = (m["f1"] or 0.0) - (base["f1"] or 0.0)
                                interval = (
                                    paired_interval(stats, base_stats, starts)
                                    if is_candidate
                                    else None
                                )
                                status = (
                                    verdict(m, uplift, interval)
                                    if is_candidate
                                    else (
                                        "BASELINE_ONLY"
                                        if not (
                                            method == "EWMAC_64_256_RESEARCH_ONLY"
                                            and family != "trend"
                                        )
                                        else "NOT_APPLICABLE"
                                    )
                                )
                                record = {
                                    "case": case,
                                    "split": split,
                                    "seed": seed,
                                    "subject": subject,
                                    "direction": direction,
                                    "method": method,
                                    **m,
                                    "unscorable_sessions": int(
                                        len(x) - 252 - valid.sum()
                                    ),
                                    "raw_alarm_count": sum(
                                        d.raw_alarm == direction for d in decisions
                                    ),
                                    "cooldown_suppressed": sum(
                                        d.suppressed and d.raw_alarm == direction
                                        for d in decisions
                                    ),
                                    "abstention_reasons": dict(
                                        Counter(
                                            d.reason
                                            for d in decisions
                                            if valid[d.session] and not d.available
                                        )
                                    ),
                                    "f1_uplift_over_fixed": (
                                        uplift if is_candidate else None
                                    ),
                                    "paired_95pct_interval": interval,
                                    "synthetic_verdict": status,
                                }
                                metricfile.write(encoded(record) + b"\n")
                                counts[status] += 1
                                if is_candidate:
                                    alarms = [
                                        d.session
                                        for d in decisions
                                        if d.alarm == direction and d.session >= 600
                                    ]
                                    diagnostic.append(
                                        {
                                            "case": case,
                                            "seed": seed,
                                            "split": split,
                                            "subject": subject,
                                            "direction": direction,
                                            "method": method,
                                            "first_alarm_after_injected_index600": (
                                                alarms[0] if alarms else None
                                            ),
                                            "pre600_alarm_count": sum(
                                                d.alarm == direction
                                                for d in decisions
                                                if d.session < 600
                                            ),
                                        }
                                    )
                    runs += 1
        print(f"{case}: {runs} completed trials", flush=True)
    with gzip_lines(output / "injected_boundary_diagnostics.jsonl.gz") as stream:
        for record in diagnostic:
            stream.write(encoded(record) + b"\n")
    report = {
        "task_id": "6B-2J-B",
        "data_kind": "SYNTHETIC_ONLY",
        "trials": runs,
        "cases": len(CASES),
        "seeds_per_case": 40,
        "metrics_rows": sum(counts.values()),
        "verdict_counts": dict(counts),
        "integrity_violations": dict(integrity),
        "integrity_checks": dict(checked),
        "implementation_conformance": (
            "PASS" if not any(integrity.values()) else "FAIL_INTEGRITY"
        ),
        "market_effectiveness": "NOT_TESTED",
        "real_validation": "BLOCKED_DATA",
        "production_enabled": False,
        "candidate_freeze_commit": "NOT_YET_FROZEN",
        "confirmation_started": False,
        "candidate_selection": "NOT_PERFORMED_REAL_DEVELOPMENT_BLOCKED; synthetic per-run gates do not select production candidates",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "calendar_version": calendar.calendar_version,
        "session_first": sessions[0].session_id,
        "session_last": sessions[-1].session_id,
        "protocol_lock": lock,
        "bootstrap": "40-session moving blocks, 1000 replicates, PCG64 seed627; same draws all subjects/methods; full chronology matched once; no rematching",
        "limitations": [
            "CUSUM drift alarms may not match trend sign-reversal targets",
            "EWMAC applies to trend only; not fabricated as volatility/relationship baseline",
            "One synthetic run may have insufficient targets; independent trials never pooled for promotion",
            "No production/runtime integration or real provider calls",
            "Native 3A acceptance remains separate and NOT_READY",
        ],
    }
    write_json(output / "report.json", report)
    write_json(
        output / "session_grid.json",
        {
            "calendar_version": calendar.calendar_version,
            "sessions": [
                {
                    "session": i,
                    "session_id": s.session_id,
                    "cutoff": s.decision_cutoff.isoformat(),
                }
                for i, s in enumerate(sessions)
            ],
        },
    )
    files = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in output.iterdir()
        if f.is_file()
    }
    write_json(output / "artifact_hashes.json", files)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
