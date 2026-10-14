# P2-H4 historical market-event acceptance

The existing sealed Q1 SPY/QQQ/IWM SIP CSV contains 145,553 source bars. This
checkpoint converts its 70,200 regular-session bars into 70,201 normalized
deliveries including one connection message. The source/universe calendar has
60 sessions, with 40 active after the unchanged 2025-02-01 decision cutoff.
Canonical receipt clocks are assumed at minute end, not historical observations.
Hashes and aggregates are in [acceptance.json](acceptance.json); raw trace and
journals stay local.

All 70,200 bars are accepted without gaps, conflicts or late messages. The fixed
INTRA-1B delayed-half-fill profile yields the same 60 modeled fills as P2-H2,
matching symbol, side, quantity, decision/execution times, reason, commission and
cash delta. It completes 15 round trips and 30 exit fragments, with ending cash
99,322.90005194, no broker positions and no active orders. Cash-flow sums agree.
The new event contract adds audit and changes the namespace/hash; economic
parity, rather than old journal byte identity, is the control.

Pause after 1,000 minutes retains 1,002 frames. Resume verifies 1,002 and appends
22,459. Repeat verifies all 23,461 frames and appends zero with the identical new
chain. Changed event receipt timing is refused by the sealed resume contract.

Twenty-five new integration cases cover canonical ORB/RVOL partial-fill parity,
delivery/bar duplicates, timely versus post-cutoff revisions, stale versions,
content conflict quarantine, late bars without retrospective gap repair,
reconnect/SYNC coverage, delivery sequence gaps, source/identity/clock ambiguity,
envelope validation, future-trace causal prefix comparisons, resume/deduplication,
post-session final audit, event file seals, credential-free CLI, cancellation of
unfilled entry tranches during outage, post-signal pending-entry gates and UTC
equivalence across sender timezone offsets, and an entirely missing final
session retained in the calendar/daily quality report. The original lifecycle/runner/data
checks remain enabled. Ubuntu/Windows CI also converts, inspects and runs a
supervised synthetic event trace.

The event compiler builds a sealed historical input before replay. The execution
ledger still uses modeled OHLC opens/intervals, rather than measured network fill
availability. This is not an incremental live trading loop. Missing/outage/
post-cutoff correction evidence keeps acceptance incomplete even when forward
readiness recovers; such runs suppress admissible PnL/drawdown. The source period
was already inspected and is not an untouched profitability evaluation.

Next: P2-H5 incremental historical Shadow processing, receiver cursors, bounded
queues/watermarks, restart and backpressure checks. Paid realtime access, actual
orders and strategy parameter optimization remain deferred.
