# 6B-2I-3 — source-clock pilot start

**Implementation validation PASS; real pilot COLLECTING; data admission BLOCKED_DATA.**

The frozen protocol declares 20 consecutive XNYS decisions, 2026-10-08 through
2026-11-04. It fixes four post-close polling offsets and the >=95% per-core-feed
coverage threshold. Six official clock documents are captured with actual UTC
first-seen times and hashes. VIX receives a regular-session conservative bound;
Treasury bounds are explicitly provisional and HY remains unverified.

A separate v2 profile namespace reuses the existing raw journal without overwriting
v1 bindings. A genuine 24-response diagnostic probe after implementation freeze
(19 feeds, five metadata pages; all HTTP 200) validates the live path. This was
before the first pilot cutoff: completed pilot samples are zero and coverage is
null. No 20-day result, historical availability or S/D effectiveness is claimed.

`pre_pilot_cutoff_diagnostic.json` retains the separate 2026-10-07 v1 decision:
only 1/13 active required sensors available. New late captures do not repair it.
This predates the newly frozen pilot and is explicitly shown rather than treated
as a successful observation or hidden from prior collection history.

A local worker was started and its live PID/heartbeat verified. The launch artifact
is an observation, not an uptime guarantee. This environment has no durable
scheduler; suspension/restart can interrupt collection. Missing decisions stay
in the denominator and require resumption using the same raw store and protocol.

`bootstrap_coverage_report.json` contains the current empty pilot result and
capture parse diagnostics. `source_admission_matrix.json` separates per-source
clock status from pending operating coverage. `v2_binding_manifest.json` anchors
initial binding validation to raw/metadata/clock capture IDs. Source series values
and raw responses remain local; this archive contains hashes, counts and status.

See [architecture and commands](../../../docs/architecture/sentinel-source-clock-pilot.md).
Frozen G/I contracts, experiment locks and original bibliography remain unchanged.
