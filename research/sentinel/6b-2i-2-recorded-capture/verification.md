# Verification

- Full default regression: **531 passed, 1 network test deselected**, 119.49 s.
- Nine focused capture tests cover exclusive creation, payload/binding integrity,
  unknown publication times, stable binding identity, incomplete scalar/ETF rows,
  future cutoff rejection, exact calendar warmup, metadata unit rejection,
  metadata availability and nontrivial later-revision causal replay.
- Two explicit real capture rounds: 19 feeds and five FRED metadata pages each;
  all 48 responses HTTP 200 and all feed research profile checks pass.
- Both full-record snapshots equal cutoff-prefix snapshots. Snapshot and S/D
  reference IDs agree across both rounds at the same original decision cutoff.
- Latest completed decision: 2026-10-06. Actual first captures are on 2026-10-07.
  Snapshot/S/D remain unavailable; eligible cutoff points and elapsed monitored
  decisions are zero. Operating coverage is null, admission BLOCKED_DATA.
- Prior I-1 artifact hashes verified after the explicit unsent-request correction.
- Frozen G protocol/lock, original bibliography, I protocol/lock unchanged.
- TODO content from `# Historical / Legacy Roadmap` onward is byte-identical to
  baseline main c6be0c185914632ef8bbfef4bf6aee50160d37fa.
- `git diff --check` passes. Raw response payloads and numeric series stay local.

The exclusion of the network pytest marker is separate from the two online
capture runs explicitly executed and archived here. No production admission,
prospective experiment, deployment or scheduler was performed.
