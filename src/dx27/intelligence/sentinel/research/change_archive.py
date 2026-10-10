"""Archive all metrics, two prespecified evidence seeds per case and exact replay audit."""

import argparse
import gzip
import json
import hashlib
import shutil
import collections
import zlib
from pathlib import Path
from dataclasses import asdict
import numpy as np
from dx27.intelligence.sentinel.research.change_detection import replay, METHODS
from dx27.intelligence.sentinel.research.change_inputs import (
    generate,
    subjects,
    CASES,
    history_changes,
)
from dx27.intelligence.sentinel.research.change_synthetic import (
    encoded,
    gzip_lines,
    verify_protocol,
)


def archive(src, dst):
    protocol, lock = verify_protocol(Path("."))
    hashes = json.loads((src / "artifact_hashes.json").read_bytes())
    for name, expected in hashes.items():
        if (
            Path(name).name != name
            or hashlib.sha256((src / name).read_bytes()).hexdigest() != expected
        ):
            raise ValueError("full execution artifact hash mismatch")
    report = json.loads((src / "report.json").read_bytes())
    if report["protocol_lock"] != lock:
        raise ValueError("execution protocol differs from frozen protocol")
    dst.mkdir(parents=True, exist_ok=False)
    shutil.copy2(src / "report.json", dst / "source_execution_report.json")
    shutil.copy2(src / "artifact_hashes.json", dst / "full_execution_hashes.json")
    shutil.copy2(src / "session_grid.json", dst / "session_grid.json")
    shutil.copy2(src / "revision_oracle.json", dst / "revision_oracle.json")
    replay_inputs = {}
    summary = collections.defaultdict(list)
    failures = []
    checked = 0
    violations = collections.Counter(
        {
            k: 0
            for k in json.loads(
                Path(
                    "research/sentinel/6b-2j-a-change-protocol/protocol.json"
                ).read_bytes()
            )["synthetic_plan"]["correctness_gates"]
        }
    )
    representative_rows = 0
    for case in CASES:
        shutil.copy2(src / f"{case}-metrics.jsonl.gz", dst / f"{case}-metrics.jsonl.gz")
        with gzip.open(src / f"{case}-metrics.jsonl.gz", "rt") as stream:
            for line in stream:
                v = json.loads(line)
                if v["method"] in METHODS[-2:]:
                    summary[
                        (case, v["split"], v["subject"], v["direction"], v["method"])
                    ].append(v)
                    if v["synthetic_verdict"] == "FAIL":
                        failures.append(v)
        # Store complete snapshots/lineage/alarms/matches for both registered seed partitions' first seed.
        with gzip.open(src / f"{case}-evidence.jsonl.gz", "rt") as stream, gzip_lines(
            dst / f"{case}-representative-evidence.jsonl.gz"
        ) as target:
            for line in stream:
                v = json.loads(line)
                if v["seed"] not in (62700, 62800):
                    continue
                target.write(encoded(v) + b"\n")
                representative_rows += 1
                if v["type"] == "stream":
                    key = (case, v["seed"])
                    if key not in replay_inputs:
                        online, _, _ = generate(case, v["seed"])
                        replay_inputs[key] = (
                            subjects(online),
                            {
                                subject: history_changes(online, subject)
                                for subject in subjects(online)
                            },
                        )
                    x = replay_inputs[key][0][v["subject"]]
                    updates = replay_inputs[key][1][v["subject"]]
                    if v["history_updates"] != [
                        asdict(u) | {"lineage": list(u.lineage)} for u in updates
                    ]:
                        raise ValueError("historical revision provenance mismatch")
                    columns = v["decision_columns"]
                    n = len(x)
                    missing = np.r_[0, np.cumsum(~np.isfinite(x))]
                    ready = np.zeros(n, dtype=bool)
                    ready[252:] = (missing[252:n] - missing[: n - 252]) == 0
                    available = np.asarray(columns["available"])
                    alarm = np.asarray(columns["alarm"])
                    violations["warmup_or_gap_violations"] += int(
                        np.sum((available | (alarm != 0)) & ~ready)
                    )
                    violations["missing_as_zero_or_participation_mislabel"] += int(
                        np.sum((available | (alarm != 0)) & ~np.isfinite(x))
                    )
                    decisions = replay(
                        x, v["subject"].split(":")[0], v["method"], updates
                    )
                    prefix = replay(
                        x[:650], v["subject"].split(":")[0], v["method"], updates
                    )
                    changed = x.copy()
                    changed[650:] += 1
                    future = replay(
                        changed, v["subject"].split(":")[0], v["method"], updates
                    )
                    violations["prefix_replay_mismatches"] += sum(
                        a != b for a, b in zip(prefix, decisions[:650])
                    )
                    violations["future_perturbation_changes_past_outputs"] += sum(
                        a != b for a, b in zip(future[:650], decisions[:650])
                    )
                    # Ensure the final source (including gzip-only changes) exactly replays retained original evidence.
                    for key, values in columns.items():
                        if values != [getattr(d, key) for d in decisions]:
                            raise ValueError(
                                f"retained evidence replay mismatch: {case}/{v['seed']}/{v['method']}/{key}"
                            )
                    matches = v["matches"]
                    violations["duplicate_one_to_one_matches"] += int(
                        len({m[0] for m in matches}) != len(matches)
                        or len({m[1] for m in matches}) != len(matches)
                    )
                    checked += 1
    # Preserve all original full-run integrity findings, normalize only a check-name alias.
    # Never erase a full-run violation outside the retained representative seeds.
    for key in violations:
        violations[key] = max(
            violations[key], report["integrity_violations"].get(key, 0)
        )
    violations["prefix_replay_mismatches"] = max(
        violations["prefix_replay_mismatches"],
        report["integrity_violations"].get("deterministic_replay_mismatches", 0),
    )
    if any(violations.values()):
        raise ValueError("synthetic integrity violation; cannot archive PASS")
    historical_alias = (
        "deterministic_replay_mismatches" in report["integrity_violations"]
    )
    report["integrity_violations"] = dict(violations)
    report["post_archive_audit"] = {
        "stream_checks": checked,
        "all_retained_streams_exactly_replayed": True,
        "warmup_after_gaps_audited": True,
        "prefix_check_name_normalized_to_frozen_protocol": historical_alias,
        "source_execution_report_preserved": True,
    }
    (dst / "report.json").write_bytes(encoded(report) + b"\n")
    records = []
    for key, values in summary.items():
        out = dict(zip(("case", "split", "subject", "direction", "method"), key))
        out["trials"] = len(values)
        out["verdict_counts"] = dict(
            collections.Counter(v["synthetic_verdict"] for v in values)
        )
        for metric in (
            "precision",
            "recall",
            "f1",
            "availability",
            "unmatched_per_252",
            "median_delay",
            "labels",
        ):
            nums = [v[metric] for v in values if v[metric] is not None]
            out[metric] = {
                "defined_trials": len(nums),
                "median": float(np.median(nums)) if nums else None,
                "minimum": min(nums) if nums else None,
                "maximum": max(nums) if nums else None,
            }
        records.append(out)
    (dst / "descriptive_summary.json").write_bytes(
        encoded(
            {
                "warning": "Descriptive across independent trials only; never pooled for promotion",
                "strata": records,
            }
        )
        + b"\n"
    )
    (dst / "numeric_failures.json").write_bytes(encoded(failures) + b"\n")
    shutil.copy2(
        src / "injected_boundary_diagnostics.jsonl.gz",
        dst / "injected_boundary_diagnostics.jsonl.gz",
    )
    manifest = {
        "full_execution_hashes": "full_execution_hashes.json",
        "full_trace_policy": "All 760 trials fully recorded in local full execution; repository retains all 38000 per-trial metric rows and both first registered seeds per case with all inputs and streams. Omitted full evidence shards regenerate deterministically via the CLI; no row is omitted from metric reporting.",
        "representative_seeds": [62700, 62800],
        "representative_evidence_rows": representative_rows,
        "numpy": np.__version__,
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        "reproduction_command": ".venv/bin/python -m dx27.intelligence.sentinel.research.change_synthetic --output work/task-6b-2j-b/reproduction",
        "report_note": "source_execution_report.json preserves original execution; report.json adds independently repeated prefix/gap and exact retained-trace audit.",
    }
    (dst / "evidence_manifest.json").write_bytes(encoded(manifest) + b"\n")
    print(
        json.dumps(
            {
                "trials": report["trials"],
                "verdicts": report["verdict_counts"],
                "audit_streams": checked,
                "violations": dict(violations),
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive(args.execution, args.output)


if __name__ == "__main__":
    main()
