# P2-H7 recorded read-only paper evidence

This stage connects recorded GET responses to H6's exact cumulative order
contract. It contains no HTTP client, credential lookup, SDK, submission, cancel
or automatic retry. The collector accepts the exact `RecordedPaperTransport`
type only. Recordings are finite single-use expected-request cassettes, not a
transport interface that can be replaced with a live broker implementation.

## Query inventory and bounded pagination

Each pass reads account, positions, open orders, every supplied known
`client_order_id`, then account activities. All paths are fixed paper GET paths.
The cassette binds each path and parameter dictionary to a recorded response,
HTTP status and UTC observation time. Unexpected queries, non-200 responses,
unconsumed tails and reused cassettes fail. Errors use stable codes and do not
include response bodies or account identifiers.

Open orders use limit 500. A full page is rejected as potentially truncated;
timestamp-only pagination can omit equal-timestamp order boundaries. This is an
explicit supported-size limit, not an implementation of complete large-account
order pagination. Up to 100 known client IDs are separately looked up, including
terminal orders absent from open inventory. Returned identities must match each
lookup, and shared open/lookup copies must agree. Missing/404/uncertain lookup
pauses reconciliation without permitting submission retry.

Activities use ascending ID-token pagination with page size 1–100 and at most
100 pages. Every full page requires another page, including an empty terminator
when necessary. Identical overlapping activity IDs are deduplicated; conflicting
IDs, nonprogressing cursors, clock regressions, malformed or oversized pages and
page exhaustion fail. Each response is limited to 256 KiB of canonical JSON;
cassettes contain at most 512 responses. These limits bound query work and
individual payloads, not streaming memory for arbitrarily large accounts.

## Execution and fee evidence

Only complete whole-share FILL histories are supported. Each fill must match its
order's symbol/side, have a positive exact price and match the running `cum_qty`.
Final cumulative quantity must equal the queried order's `filled_qty`.
Executed notional sums exact `price * qty` values with H6's bounded Decimal
precision; rounded order average price does not determine cash.

Recorded FEE/CFEE debits require explicit order ID, USD currency and exact
negative `net_amount`. They are summed by order. Account-level fees without
reliable order attribution are unsupported; no description matching or guessed
allocation is attempted. Real Alpaca fee/activity responses are not claimed to
provide these associations. No fee response does **not** mean zero fees: orders
without fee entries need a separate explicit `verified_zero_fee_orders`
attestation. Observed debits conflict with zero-fee attestations. Rebates,
corrections, busts and unknown activities pause collection.

## Coverage and coherence limits

The producer explicitly asserts `history_complete: true` for the supplied
`history_after`–`through` range. The range must start strictly before every
included order's creation, and all activity/order updates must fall within its
supported bounds. This assertion is not proof of provider history completeness,
unobserved late fees, or ownership of an account. Unknown activity orders fail;
unowned open orders remain visible to the order book's reconciliation checks.

The collector makes two entire passes over the same fixed history range. Account,
positions, orders, costs and deduplicated activity content must agree exactly.
Observation timestamps must be nondecreasing, at/after the history cutoff and
not after the caller's replay `now`. The cutoff and earliest observation must
be within five seconds of `now`. Two equal recorded observations detect visible
changes; they do not prove atomicity of separately fetched live endpoints or
absence of an unseen event between observations.

Only after both passes succeed is the bundle normalized through H6 and passed
to the existing offline persistent order book. A collection failure pauses the
book before applying any recorded fills. Cash, positions, ownership, unknown
states, duplicates and restart requirements keep the existing reconciliation
rules. Receipts expose counts, observation bounds, a deterministic evidence SHA
and explicit disabled execution flags. SHA is an integrity identifier, not
authentication of the producer.

## Acceptance and next stage

Run:

```sh
python -m pytest -q tests/integration/test_intraday_paper_evidence.py tests/integration/test_intraday_paper_contract.py
```

The 42 new evidence cases cover exact costs, overlap/terminal pages, terminal
order lookups, inconsistent snapshots, malformed/missing/unsupported history,
cursor/size/page limits, rate limits/404 without retries, nonrecorded transport
rejection, observation clocks, explicit fee attestations and no partial ledger
updates on collection failure. The positive fixture contains two fills and one
fee debit: notional 200.24691357, fee 0.1 and final cash 799.65308643 from 1000.
These are synthetic broker-response fixtures, not actual paper-account fills or
strategy performance evidence. Both platform intraday CI jobs include the suite.

Next P2-H8: a separately validated **read-only** paper HTTP recorder with fixed
host/GET allowlists, redirect and size controls, redacted diagnostics, and honest
incomplete evidence outcomes. Real fee attribution and snapshot atomicity must
remain unverified unless actual responses establish them. Submission remains
disabled; paid realtime data and algorithm tuning remain deferred.
