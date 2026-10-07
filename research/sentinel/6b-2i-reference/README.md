# 6B-2I Reference Research Checkpoint

- Implementation correctness: PASS (synthetic evidence only).
- Real source admission / incremental effectiveness: BLOCKED_DATA.
- Prospective confirmation: INSUFFICIENT_EVIDENCE, zero sessions, not started.
- Operational references, change detectors, forecasts, composite Priority: disabled.

The [architecture checkpoint](../../../docs/architecture/sentinel-composite-reference-research.md)
explains implementation, formula/window choices, source issues, and the remaining
gates. The [reference library](../references/README.md) gives stable literature IDs
for every sensor and feed, with explicit verification limits.

`experiment_protocol.json` preregisters the four-arm comparison and exact fixed
logistic fitting choices. `experiment_lock.json` locks that file and the two
bibliography/mapping files. Its final fitted candidate is NOT_YET_FROZEN:
source admission and development fitting must precede registration of a candidate
commit and prospective collection. No audit or prospective AUC was measured here.

`source_capture_manifest.json` and `yahoo_capture_manifest.json` retain actual
network capture hashes and UTC first-seen times. Raw captured content is local
research material, excluded from this repository. Metadata-only HTML responses
are not counted as observation series. `source_admission_report.json` records
history and timestamp blockers; source definitions are not approved bindings.

`reference_conformance_report.json` records independent formulas, prefix replay,
synthetic explanation scenarios, and descriptive sensitivity. It records the
source implementation commit; `reference_sample.json` contains typed references
with resolvable measurement IDs in the synthetic tape. Rebuild that tape through
the runner, whose `synthetic_tape_digest` pins the exact evidence.
`sensor_reference_annotations.json` joins each runtime descriptor/version to the
protocol and bibliography/mapping digests. `artifact_hashes.json` pins the
conformance artifacts, and `verification.md` records validation.

Frozen EWMAC results and G protocol/lock remain unchanged. This task stays within
6B-2; it does not silently start 6B-2J or 6B-2K.
