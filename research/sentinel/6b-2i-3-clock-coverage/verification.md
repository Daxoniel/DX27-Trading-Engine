# Verification

- Default regression: **540 passed, 1 network test deselected**, 133.77 s.
- Focused recorded-capture plus pilot suite: **18 passed**, 10.57 s.
- Tests cover real-bound DST/early-close policy, publication-time non-inference,
  future clock evidence, preserved v1 namespace, complete 13-sensor synthetic
  state versus HY age-zero insufficiency, missed-day denominator, later-revision
  snapshot stability, null rates before cutoffs, idempotent slots, HTTP failure
  and retry separation, job journal tampering and frozen consecutive sessions.
- Six official documents captured successfully. Frozen-code live probe produced
  24 HTTP-200 responses; no raw series was committed.
- Real bootstrap pilot: 0 completed cutoffs, null coverage, INSUFFICIENT_SAMPLE.
- Separate previous v1 cutoff (2026-10-07): DEGRADED, 1/13 active required sensors;
  causal-prefix replay PASS. It is not counted as a completed new pilot decision.
- Worker heartbeat and PID checked at the time in `worker_launch_observation.json`.
  This does not establish future runtime availability or completed collection.
- Prior I-1/I-2 artifact SHA-256 indices verified. Pilot protocol/clock locks pass.
- Frozen G protocol/lock, original bibliography, I experiment protocol/lock unchanged.
- Historical/Legacy TODO suffix byte-identical to merged main f1c85270dcb9fd31ade1bc2db3d40889ecca5415.
- `git diff --check` passes.

The network pytest marker exclusion is independent from the explicitly executed
real document captures and live provider probe. Synthetic test rows are not real
pilot evidence. No production promotion, fitted candidate or prospective model
experiment was started. Twenty-session pilot acceptance remains outstanding.
