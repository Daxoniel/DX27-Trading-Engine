# MLP2 portfolio replay: conditional historical diagnostic

The primary run stops on a missing held-position bar. It does **not** establish
a complete-period return. The separately preregistered observed-bars-only
diagnostics cannot replace that failed completeness result or authorize Paper
orders. All runs use the already examined 2025 period, not an independent test.

Protocol: [replay-v2-protocol.json](../../research/martin-luk/replay-v2-protocol.json).
Method and reproduction: [replay-v2.md](../../research/martin-luk/replay-v2.md).
The original MLP1 implementation and MLP2 scanner remain unchanged.

## First held-bar gap: why no bar does not mean no trade

The primary stops on SLNO at 2025-04-29 16:20 UTC, session 2. No minute bars
are returned inside that five-minute interval, although flanking minutes have
bars. A separate historical SIP trade request returns 26 trades: 25 carry odd
lot condition `I`; the remaining trade carries average-price `W` and derivative
price `4`. Every trade has at least `I` or `W`.

Alpaca's [official aggregation rules](https://docs.alpaca.markets/us/docs/market-data-faq)
say that `I` and `W` do not update OHLC prices, that the strictest condition
applies when several coexist, and that incomplete OHLC bars are not emitted.
The observed absence is therefore consistent with documented aggregation,
rather than evidence that no trading occurred or proof of a feed outage.
It does not establish executable prices for the strategy's protective orders.
No fabricated flat bar was inserted and the primary halt was not erased.

Probe evidence is summarized without trade prices in
[gap-investigation.json](gap-investigation.json) and
[gap-trades-summary.json](gap-trades-summary.json). The raw response stays private.
Other absent bars have not all been individually classified by trade condition.

## Data, execution and accounting limits

Supplemental capture adds 1,050,135 raw five-minute rows in 466 cached response
pages, including SPY corporate actions. There are 453 normalized raw symbol
files: 452 candidate names and SPY. Existing source rows are reused with hashes;
overlapping source revisions cannot silently replace recorded values. Raw data
and full trade/account ledgers remain private.

Each signal becomes available one second after its five-minute close. Entry
is only at a later five-minute open within the limit after adverse cost. This
coarse delay, absence of bid/ask and unverified explicit fees prevent a claim
of executable performance. The observed-only diagnostic carries stale marks
across absent bars and processes orders at the next observed bar; its return
is neither an estimate of fills inside gaps nor a guaranteed performance bound.

Daily exits use previous vendor daily close and EMA9, with liquidation at the
next observed regular open. A triggered liquidation persists across an entire
unobserved session, even if a later daily EMA recovers. A regression test covers
this execution fix; no selection thresholds were tuned to returns.

The archived fixed name-filter cohort is not a certified dynamic common-stock
universe. Sector classifications and tradability are not historically verified.
Final revised bars and retrospective actions do not establish first availability.
Daily AVWAP and the higher-low/base proxy do not reproduce Luk's discretion.
No same-session reentry, overnight protective fill, interest, contributions,
tax withholding or dividend reinvestment is modeled. Cash dividends use gross
entitlements and remain receivables until payable. Unresolved held corporate
actions/fractional entitlements halt both gap policies.

The SPY comparison starts at the same initial regular open with the 5-bp entry
cost, holds whole shares, retains gross dividends in cash/receivables and marks
the final regular close without a forced sale. It is a period-specific passive
comparison, not a benchmark-adjusted causal estimate of skill.

Source/input seals: [source-manifest.json](source-manifest.json),
[input-manifest.json](input-manifest.json),
[protocol-publication.json](protocol-publication.json). The protocol was public
before supplemental capture; the input manifest and final execution code were
published before the final replay outcomes. Earlier interrupted diagnostics
and the first primary gap were visible during implementation verification.
