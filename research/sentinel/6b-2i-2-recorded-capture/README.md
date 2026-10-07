# 6B-2I-2 recorded capture validation

Implementation commit is pinned in `capture_manifest.json`. Two real rounds on
2026-10-07 captured 19 feeds plus five FRED metadata pages each (48 responses).
All HTTP responses and research schema checks succeeded. Raw bytes are retained
in the local persistent store; this archive contains metadata, hashes and counts.
`binding_manifest.json` records stable initial bindings and their evidence IDs.
Both replays match the cutoff-eligible prefix and produce the same snapshot ID
for the latest completed decision, 2026-10-06. S and D are unavailable.

**Implementation validation PASS; data admission BLOCKED_DATA.** The captures were
made before 2026-10-07's session close. Yesterday's cutoff cannot use today's
first-seen data. No monitored cutoff has yet elapsed, so operating coverage is
null. This is bootstrap validation, not historical or prospective effectiveness.

`history_requirements.json` calculates 252 prior measurement sessions and each
feed's additional price lookback using XNYS. `supplier_request_correction.json`
records the authorized correction to the prepared, unsent HY supplier request
and its old/new SHA-256; its audit captures/conclusions are unchanged.

See [architecture and repeatable commands](../../../docs/architecture/sentinel-recorded-capture.md).
The local collector requests two years for Yahoo live bootstrap; the 2003/2004
raw-history requirements belong to the separate historical acquisition plan.
Frozen G protocol, original bibliography and I experiment locks remain unchanged.
