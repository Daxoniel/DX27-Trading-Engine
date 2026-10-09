# 6B-2I-3A — Durable Pilot Runner & Recovery Validation

Implementation preparation is complete; durable deployment remains **NOT_READY**.

Windows operation instructions: `docs/operations/sentinel-windows-pilot.md`.
Architecture: `docs/architecture/sentinel-durable-runner.md`.

Validation: full regression 547 passed, 1 network test deselected (134.00 s). After adding the missing-store rejection guard, focused capture/coverage/durability tests: 26 passed (10.62 s). Local quiesced backup and restore preserved 102 captures and 353 files byte-for-byte. Native Windows execution, reboot recovery, logged-out operation, final single-writer handoff and actual external alarm/recovery email receipt remain pending.

The private raw journal archive is not committed. `migration_checkpoint.json` records its checksums and local verification; it is a preparatory checkpoint, not final deployment evidence. The temporary environment collector remains a best-effort fallback until the target is ready for final handoff.

No frozen research protocol, polling rule, denominator, source availability timestamp or pilot date is reset. Pilot coverage remains pending; historical S/D support is insufficient; data admission remains BLOCKED_DATA.

## Deployment acceptance update — 2026-10-09

Historical preparation/pending files above are preserved. Current status is
NOT_READY_REQUIRED_ACCEPTANCE_EVIDENCE_PENDING; the previous PASS interpretation
is withdrawn. See deployment_acceptance.json for reported evidence, verified handoff
and required remaining tests. None became optional. Data admission stays blocked.
