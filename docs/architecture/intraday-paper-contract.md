# P2-H6 recorded paper adapter contract

This stage adds **offline response contracts**, not an Alpaca execution client.
`paper_contract.py` imports no HTTP SDK, credentials or sockets. Existing
historical strategy/sizing/execution behavior is unchanged. The prior read-only
account probe remains separate; this stage does not call it or extend its paths.

## Response identity and accounting

`normalize_order` translates recorded REST order objects into the existing
cumulative `OrderReport`. `normalize_trade_update` uses the enclosed order as the
same authority; notification quantities/prices are never added as fresh fills.
Equivalent normalized REST and stream responses have the same SHA-256 event ID.
An order's required UTC `updated_at` becomes an integer nanosecond revision,
preserving up to nine fractional digits. The envelope receipt clock never
overrides it. Changed normalized totals at the same revision cause the existing
persistent order book to halt, rather than inventing an ordering.

Only simple regular-hours DAY market orders for whole-share US equities are
accepted. `new`, `pending_new`, and `accepted` mean broker-known, unfilled
(`accepted` internally). Partial, filled, canceled, expired and rejected responses
use the existing lifecycle validation. Pending cancel/replace, replacements,
trade busts/corrections, fractional/notional/extended-hours and multi-leg orders
are unsupported and pause the review path. They are not silently translated into
successful cancellations or fills.

Both **cumulative executed notional and cumulative fees are required independent
evidence**. No fee defaults to zero; the displayed rounded average price is
validated but is not multiplied into a cash movement. Notional/fee evidence
must already be associated with the same cumulative order version. Real activity
aggregation and late commission revisions are not implemented here. A changed
fee at an unchanged order revision conflicts and halts; synthetic revisions are
not manufactured to make it pass. Values remain exact bounded Decimal amounts
with at most eight fractional digits.

## Complete recorded reconciliation

`recorded_snapshot` consumes an in-memory bundle with:

- exact paper endpoint, `complete: true`, `coherent: true`, UTC `captured_at`;
- USD account cash, unique long whole-share equity positions;
- one latest order per broker/client identity, including terminal local orders;
- exact-cover `cumulative_fees` and `cumulative_notionals` maps by broker order ID.

Completeness/coherence are explicit fixture-producer assertions. They do not
prove atomicity of future live HTTP calls. Open-orders-only responses are not a
complete local-order inventory. The full bundle is normalized before any report
is applied. Missing/malformed evidence pauses reconciliation. Unknown orders,
missing local lookups, stale reports, cash/position mismatches and unresolved
cancellation states are handled by the existing offline order book. A missing
lookup never authorizes resubmission. Restart still requires a complete fresh
reconciliation; duplicate updates alone cannot re-enable admission.

`apply_recorded_update` pauses on unsupported data. A subsequent valid update does
not clear this pause: a complete consistent reconciliation is required. Conflicting
reports retain the existing durable integrity halt.

## Preflight and disabled gateway

`review_admission` reviews book reconciliation, paper endpoint, explicit active
USD account/unblocked flags, matching active/tradable equity asset and open clock.
The caller supplies a replay `now`; snapshot and market clock must each be no
more than five seconds old and not in the future. `review_ready` means only these
data/account checks passed. It is not complete regulatory, sizing, reservation,
strategy-risk or order approval. Existing strategy risk and book checks remain
necessary. This helper does not persist/prepare/claim an order.

`DisabledPaperGateway.submit/cancel` always raise `PAPER_EXECUTION_DISABLED`.
There is no transport, credential lookup, enable parameter, retry or fallback.
Preflight always returns `execution_enabled: false`, even when review-ready.

## Acceptance and next stage

Credential-free integration tests exercise REST/update identity, nanosecond
ordering, unsupported shapes, required fee/notional evidence, rounded average
independence, partial/cancel/fill races, restart, duplicate/stale/conflicting
responses, missing/unowned orders, mismatched accounts, invalid full bundles,
admission freshness and gateway no-effects with socket calls forbidden.

Run `python -m pytest -q tests/integration/test_intraday_paper_contract.py`.
Both Ubuntu and Windows intraday CI include this suite.

Next P2-H7: design and validate the read-only paper order/activity lookup boundary,
pagination/completeness, coherent observation windows and fee/notional evidence
aggregation with recorded transports before any real submission. Live execution,
paid realtime data and algorithm optimization remain deferred.
