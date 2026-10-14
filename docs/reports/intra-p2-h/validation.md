# P2-H1 offline execution acceptance

2026-10-14. [Machine-readable evidence](acceptance.json) contains aggregate ledger
checks and audit seals. All reports, submit/cancel calls and broker IDs are local
simulation artifacts. No credentials, realtime subscription or Alpaca orders were
used for this checkpoint.

## Scripted lifecycle cases

All nine CLI scenarios meet their expected outcomes: partial cancellation,
reject/expiry, lost submit acknowledgement, not-found submit outcome, lost cancel
acknowledgement, fill/cancel race, cash mismatch, budget breach and restart after a
remote partial fill. Not-found stays UNKNOWN and paused; an acknowledged remote
order is recovered using the original client ID without a second submission.
A partial cancel retains four filled shares and $9,599.65 of the original
$10,000. Rejection/expiry leave account balances unchanged. A valid budget-breach
report is recorded as -$9.35 cash / ten shares and remains halted, not discarded.

37 new integration checks additionally cover exact cumulative accounting,
duplicate/stale/same-revision handling, conflicting report refusal, source/config
identity, unsent intent abandonment, reservations, late fees, late fills after
cancel, snapshot failures, state corruption and the single-writer lease. Two
child processes exit abruptly after a durable submission claim, either before
remote acceptance or after an independently committed remote partial fill.
Restart respectively stays UNKNOWN or recovers PARTIAL without blindly resending.
A prepared exit is not submitted if a late fill consumed its reserved shares.
Pending sell fees cannot consume an already prepared buy's cash allocation.

## Authentic historical trace

The source is the completed [P1-H Q1 SIP Shadow journal](../intra-p1-h/validation.md).
CSV/archive seals match the previous 145,553-source-bar, 60-session data. The
source is read-only; no strategy thresholds, costs, universe or data period were
changed. Each modeled fill becomes a stable whole-share request, followed by
partial/final cumulative simulator reports and an injected duplicate partial.

| Fixed source | Orders / partial reports | Final modeled cash | Residual versus original |
| --- | ---: | ---: | ---: |
| INTRA-1A | 92 / 92 | $98,293.37199075 | -$0.00000000002 |
| INTRA-1B | 30 / 30 | $99,194.33766854 | -$0.00000000901 |
| INTRA-1B repeated state | 30 / 0 new | $99,194.33766854 | -$0.00000000901 |

Every source order finishes FILLED; both ledgers finish with no positions and
exactly match their independent scripted broker snapshots. The original modeled
cash residual is below $0.000001. The repeated filtered trace performs **zero new
submit calls**, retains 30 orders and has no new partial reports.

These are already inspected source fills: both original configurations lost money
in Q1. They are not an untouched evaluation set or strategy-effectiveness result.
Splitting fixed fills verifies lifecycle accounting but does not change the
strategy's subsequent decisions under delayed/partial execution.

## Software checks and remaining gates

Local Linux regression: **963 passed, 1 network test deselected**. Intraday suite:
**148 passed**, including 37 new checks. Existing Sentinel Yahoo empty-slice
warnings remain unchanged. Ubuntu/Windows CI runs the same intraday suite, a
historical Shadow demo and the offline lifecycle/partial-fill trace demo. Final
cross-platform CI status is recorded in the PR.

Raw market data, full simulated order/ledger state, broker state and local logs
remain under ignored `work/`. The public repository contains only code, synthetic
contracts, aggregate acceptance and seals.

Next: P2-H2 historical decision/account feedback under asynchronous executions.
Actual Alpaca normalization, entitlements, market orders/fills, provider-side
idempotency, stream ordering and broker reconciliation are not validated here.
`real_broker_orders_enabled=false`, `realtime_data_verified=false`,
`strategy_execution_feedback_verified=false`, `effectiveness=NOT_EVALUATED`.
