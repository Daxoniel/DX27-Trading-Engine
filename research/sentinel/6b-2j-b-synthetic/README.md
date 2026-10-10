# 6B-2J-B — Frozen synthetic research execution

760 trials / 19 cases / 40 seeds per case. Implementation conformance PASS;
15,186 candidate strata INSUFFICIENT_EVIDENCE, 14 FAIL, zero PASS. Market efficacy
NOT_TESTED, real validation BLOCKED_DATA, production disabled, no final freeze.

`report.json` is the canonical report plus exact retained-trace/gap audit.
`source_execution_report.json` preserves the original execution report.
`*-metrics.jsonl.gz` contains every seed/subject/direction/method metric and interval.
`*-representative-evidence.jsonl.gz` retains full input journal, immutable snapshots,
lineage, decision columns and matches for seeds 62700 and 62800 in every case.
`full_execution_hashes.json` records original full output hashes, including omitted
large full-evidence shards, which regenerate using the documented CLI.

`descriptive_summary.json` summarizes independent trials for review only; it never
rescues an insufficient/failed stratum or selects a production model.
`numeric_failures.json` enumerates all 14 failures. Injected-boundary diagnostic
alarm times are separate from the frozen future-label scoring and give no extra
matching credit. See the architecture document for limitations and reproduction.

Historical revisions now update later-cutoff numerical windows and constituent
provenance without replaying original snapshots, accumulators or past alarms.
`revision_oracle.json` records 160 independent capture-journal cutoff checks over
all 40 registered revision seeds. `revision_comparison.json` counts changed metric
rows against the preceding reviewed execution: 6 revision rows and 80 delayed
rows changed, while candidate verdict totals remain unchanged.
