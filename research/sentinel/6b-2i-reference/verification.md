# 6B-2I Verification

Implementation conformance source commit: `75874a1646d596c2525e4476f008a8dffa8c8fb8`.
The follow-up commit `1d9cfa3` separates known-history numeric audit PASS/FAIL from
market-effectiveness qualification. It changes only the experiment result labels;
reference/library/conformance runtime code remains byte-identical to the recorded
conformance commit. Its four experiment tests pass.

- Full offline suite: **514 passed, 1 network test deselected**.
- Focused S/D/library/experiment suite: **14 passed**, including full 252-session
  reference windows and the extra prior observation needed for correct delta.
- Two standalone conformance runs: all four JSON artifacts byte-identical.
- 24 decision snapshots, **48** independent NumPy S/D comparisons.
- Maximum absolute formula error: **7.105427357601002e-15**, below 1e-10.
- Prefix replay mismatches: **0**; reversed/duplicated history is deterministic.
- Historical lagged samples excluded; current delayed HY produces null STALE S
  with 4/5 supported members and independently available D. No reweighting.
- Zero-MAD, insufficient-history, missing-previous-snapshot, conflicting-history,
  descriptive-vintage, contribution and contract-field checks pass.
- Four synthetic explanation scenarios and 13 descriptive sensitivity variants.
- Stable bibliography: **18 references, 19 feeds, 18 sensor contracts**; unknown
  reference IDs and mismatched protocol digests rejected.
- Fixed logistic convergence verified against gradient stationarity; AUC ties,
  running-peak drawdown labels, complete follow-up and unshifted grid checks pass.
- Compile checks, JSON parsing, local documentation links and `git diff --check`
  pass. Frozen G protocol/lock, EWMAC archive and legacy TODO remain unchanged.

Actual online probe: Yahoo SPY/RSP/QQQ/IWM each 25 rows; Cboe VIX 9,288 rows.
Capture hashes and actual first-seen timestamps retained. No historic publication
or approved vintage/binding inferred from these downloads. HY graph is HTML;
metadata documents the three-year history limit and an observed delayed release.

Real source/operational coverage and incremental effectiveness: **BLOCKED_DATA**.
Prospective confirmation: **INSUFFICIENT_EVIDENCE**, zero sessions, not started.
No logistic fit or AUC effectiveness comparison was performed on real data here.
Final fitted candidate remains unfrozen; no current commit is registered as a
prospective start. Operational reference/report attachments, detectors, forecasts
and composite Priority remain disabled.
