# P2-H3 operational runner acceptance

The unchanged Q1 SPY/QQQ/IWM historical SIP source has 145,553 input bars,
70,200 regular-session bars and 60 sessions; February activation leaves
40 active sessions. Read-only preflight reports no missing regular bars or
zero-volume bars. It creates no journal, lease or runtime directory.

The same fixed INTRA-1B delayed-half-fill profile used in P2-H2 is supervised
without strategy changes. Pause after 1,000 minutes leaves 1,002 committed frames.
Resume verifies 1,002 and appends 22,459; completed repeat verifies 23,461 and
appends zero. The final journal chain exactly matches the prior P2-H2 acceptance
chain, as does ending cash 99,322.90005194. Cash flows reconcile, simulator
positions are empty and active orders are zero. Final health is COMPLETED with
released ownership. Aggregate receipts are in [acceptance.json](acceptance.json).

Nineteen new integration cases exercise read-only preflight and quality flags,
managed pause/resume/repeat equivalence, commit-boundary stop requests, stale
attempt requests, runner/journal writer contention, changed manifests and
corrupt journals, path aliases, interrupted/stalled monitoring, transient failure
reconstruction, no retries for validation or disk-full, exhausted restart budget,
subprocess death, unresolved-order incompleteness, unavailable health storage,
report-write failure, credential-free CLI and source/session gates. POSIX CLI
SIGTERM is checked at a known committed frame; Windows process termination does
not deliver that handler, so that single test is skipped there. Both platforms
still check forced process death, lease release and prefix recovery. A subprocess
also exits during an uncommitted SQLite transaction: preflight leaves the hot
rollback files unchanged, then the managed run recovers under both leases and
verifies the original committed prefix.

This is historical operational conformance, not live broker supervision or
profitability evidence. The source period was already inspected. Automatic
restarts are bounded and opt-in; unknown orders are not automatically retried.
Paid realtime data, actual paper submission and algorithm optimization remain
deferred. Next: P2-H4 provider-independent market event ingress and quality gates.
