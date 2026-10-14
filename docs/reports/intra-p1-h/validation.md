# P1-H historical Shadow acceptance

2026-10-14. Per the user's historical-first direction, realtime SIP subscription
is deferred. This checkpoint records old SIP data and modeled execution offline;
it sends no broker orders. [Machine-readable evidence](acceptance.json) contains
source seals, journal receipts and independent accounting/parity checks.

## Real input and parity

Re-downloaded SPY/QQQ/IWM `sip/raw` one-minute bars for 2025 Q1: 145,553 source
bars, 70,200 regular-session bars, 60 sessions. CSV and canonical response archive
hashes exactly match the [earlier INTRA-1A/B acceptance](../intra-1a-real/validation.md).
The same fixed engineering config and decision start of 2025-02-01 were used;
no thresholds or costs were changed.

Both recorded runs produce 23,461 committed frames: 23,400 synchronized minute
batches, 60 session-finalization batches and one run-finalization batch. Every
fills/trades/equity/daily/decisions/selection record and the final quality table
match the normal shared replay. Buy times remain strictly after decision times.
Independent cash-flow, trade-cost and equity checks have residuals below $0.000001.
Both runs finish with zero hypothetical positions.

| Fixed historical configuration | Trades | Modeled net PnL |
| --- | ---: | ---: |
| INTRA-1A, no volume filter | 46 | -$1,706.63 |
| INTRA-1B, preceding 20 openings, RVOL >= 1.0 | 15 | -$805.66 |

These match prior software acceptance; both configurations lose money in the
inspected period. This is not parameter selection, profitability approval or an
untouched evaluation set.

## Recovery

The real INTRA-1B run paused after 1,000 new minutes / 1,002 committed frames.
Resuming verified those 1,002 frames and appended 22,459 frames. Repeating the
completed run verified all 23,461 and appended **zero**; its journal chain hash
is unchanged. Recovery reconstructs the engine from the sealed source rather
than trusting a mutable state snapshot.

Nine new integration cases cover baseline/RVOL record parity, idempotent resume,
source/config drift refusal, journal corruption, single-writer lease, changed
engine output, missing minutes/warmup/early closes, causal prefix invariance and
CLI execution without credentials. A child process exits abruptly immediately
after a hypothetical buy is committed; the next process recovers identically to
uninterrupted replay, including its account and final flat position state.

The full intraday suite passes locally on Linux: **111 passed**. Cross-platform CI
runs the same suite and a synthetic historical Shadow demo; final CI status is
recorded in the PR. Raw market data, SQLite journals and complete real ledgers
stay under ignored `work/`, outside the public repository.

## Remaining gates

`realtime_data_verified=false`, `broker_orders_enabled=false`,
`effectiveness=NOT_EVALUATED`. Historical data loaded up front and assumed
minute-end availability do not demonstrate WebSocket receive ordering, actual
publication/arrival times, stream revision/backfill handling or broker fills.
Those remain distinct realtime/P2 checks. The next historical checkpoint is
P2-H offline execution lifecycle/reconciliation conformance, which can proceed
without buying realtime SIP.
