# P2-H5 incremental historical Shadow acceptance

H5 shares the H4 cutoff/revision/reconnect policy through one per-event state
machine. The unchanged regular-session Q1 trace contains 70,201 deliveries for
70,200 bars across 60 sessions, with original 145,553-bar CSV context and
February activation. The fixed INTRA-1B delayed-half-fill profile and a declared
16-item queue are used for engineering acceptance. Receipt clocks remain
historical assumptions, not observed network availability.

Pause after 1,000 minutes commits the first 1,002 frames and acknowledges 3,001
deliveries. The durable byte/line/prefix cursor excludes prefetched future events.
Resume restores receiver maps and that cursor, rebuilds strategy from the saved
minute snapshots, then parses only the remaining 67,200 events. Completed repeat
reconstructs the stored minute prefix, parses zero event JSON records and appends
zero frames. Source bytes are still scanned for integrity. Final source cursor,
chain, monetary comparisons and queue peaks are in [acceptance.json](acceptance.json).

Normal behavior is checked against the prior fixed profile: 60 fills, 15 round
trips, 30 exit fragments, identical quantities/times/reasons/commissions/cash deltas
and ending cash 99,322.90005194. Independent simulated positions are empty and
active orders are zero. These are accounting/software checks on an already
inspected period, not untouched strategy profitability validation.

Twenty-five new integration cases cover ORB/RVOL partial-fill parity without a
full trace compiler, suffix-only decoding and exact journal equivalence,
capacity-one backpressure with a large same-clock burst, failures during receiver
and pre-commit transactions, forced process death and lease release, map/cursor
corruption, changed/live-mutated sources, bounded line decoding/duplicate JSON/
clock regression, post-session final audit, attempt-specific stops and competing
writers, credential-free CLI, invalid resource limits, persistent late/conflict/
reconnect parity across restart and report failures preserving the execution
receipt. Existing H4/H3/order lifecycle cases remain enabled. Both platform CI
jobs run incremental ingestion plus a completed zero-append verification.

Only the receiver restores directly. Strategy/account state still deterministically
rebuilds from stored minute inputs into a fresh offline simulator; this never
resubmits to a real broker. Queue bounds do not claim constant memory for CSV
context/calendar/report arrays. Simulated timestamps keep the historical OHLC
convention and new minute audit labels input availability explicitly.

Next: P2-H6 paper-adapter query/update/reconciliation normalization and a disabled
execution gateway, validated using recorded/fake responses. Actual orders,
realtime entitlement and algorithm optimization remain deferred.
