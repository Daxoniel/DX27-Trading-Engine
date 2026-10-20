# MLP2 shared-account replay

Frozen protocol: [replay-v2-protocol.json](replay-v2-protocol.json).
Source mapping and unchanged numerical assumptions:
[mapping-v2.md](mapping-v2.md). No orders are sent.

The previous candidate-coverage diagnostic was not a profitability test. This
stage reuses its sealed 172 daily plans and obtains intraday data from each
symbol's first candidate session through December 31, including subsequent
sessions when the symbol is no longer on a watchlist. Existing private raw
histories are reused; overlapping values cannot silently replace one another.

## Timing and account conventions

Each completed five-minute bar becomes available at bar end plus one second
(a modeling assumption, not measured provider latency). Entry is possible only
at a later five-minute open before signal expiry and within the buy limit after
adverse cost. With this granularity, that generally means waiting almost five
minutes after the signal. No entry is invented at a signal close or intrabar
limit touch. This is a conditional OHLC execution proxy, not evidence of a
quote-level executable price. A next-minute or quote-based execution study is
not silently substituted into this run.

The shared $100,000 account reserves cash, gross exposure, sector exposure and
open stop risk for existing positions and pending orders. Stops are processed
before targets on ambiguous bars. Three-R partial sales use the unchanged
market-trigger convention. No same-name same-session reentry is added.
Explicit broker/regulatory fees remain unverified; 5/10/25 adverse basis points
per side are prespecified primary/stress assumptions, not a certified fee table.

For daily EMA9 exits, each premarket uses the previous completed **vendor daily
close** and EMA on the preceding 160 vendor daily closes, adjusted only through
effective splits. Existing holdings below that EMA exit at the first observed
regular open, with adverse cost; the recorded exit time is that open. A current
intraday close is never used in place of the vendor daily close, and a current
day's final daily bar cannot trigger a same-day exit. Protective stops remain
active on every observed regular bar. Extended-hours protection/execution is
not modeled. Final holdings are marked, not forcibly liquidated.

Primary policy HALT stops at a missing/invalid held bar, missing daily history
for a held name, or unresolved corporate action. Terminal return then remains
null. A prespecified OBSERVED_ONLY diagnostic continues across **absent** bars
with stale marks and uses the next observed bar for protection; it records
every blind interval. It does not establish what happened inside a gap, is not
a bound on actual PnL, and cannot replace a failed primary completeness result.
Invalid held bars and unresolved corporate actions halt both policies. Missing
opening-prefix bars prevent that candidate's entry, while later missing bars
never retroactively delete earlier fills.

Cash dividends accrue on ex-date as nonspendable receivables and become cash on
payable date. Splits adjust quantities and protection. Fractional entitlements,
unhandled mergers or delistings stop accounting rather than assigning zero
loss. Action records are retrospective and first availability is not verified.

## Reproduce

With the prior private cache and candidate coverage directory available:

```sh
python research/martin-luk/capture_replay_v2.py --coverage work/mlp2/coverage --old-root work/mlp1-history --output work/mlp2-replay
python research/martin-luk/prepare_replay_v2.py --coverage work/mlp2/coverage --old-root work/mlp1-history --root work/mlp2-replay
python research/martin-luk/run_replay_v2.py --manifest work/mlp2-replay/normalized/manifest.json --output work/mlp2-replay/primary
python research/martin-luk/audit_history.py --report work/mlp2-replay/primary
```

The secondary uses `--gap-policy OBSERVED_ONLY`; stress runs additionally use
`--adverse-bps 10` and `--adverse-bps 25`. These rerun the whole account, including
cost-dependent limit/size decisions, rather than merely subtracting a fixed
cost from a preferred result. The primary remains 5 bps and is not selected by
outcome. The independent Decimal audit imports neither strategy nor replay.

The SPY comparison holds whole shares funded at the first regular open plus
the same primary entry cost, retains dividends in cash/receivables and marks
the final regular close without a forced sale. It is not part of the stock
selection universe. Equity/drawdown at observed bars can miss intrabar extremes.

Raw vendor bars, detailed fills and account ledgers remain private in `work/`.
Public results contain aggregate diagnostics and input/code hashes. The fixed
archived name-filter cohort, final corrected bars, retrospective actions,
broad sector proxies and already examined 2025 period preclude independent
out-of-sample or full point-in-time claims. A profitable diagnostic alone would
not authorize strategy deployment or prove the discretionary method reproduced.

## Quote-entry correction after execution audit

The original aggregate-open entry proxy failed winner timing/quote inspection.
Its positive result is not accepted as executable evidence. The separately
frozen [quote protocol](quote-execution-protocol.json) uses latest historical
quotes at/before the scheduled opening, regular condition, no more than 60
seconds of age, ask plus cost within limit and displayed-size partial fills.
It never falls back to a later trade-bar open. Original inputs and results
remain sealed. See the [final report](../../reports/martin-luk-v2-replay/README.md).

Official schemas: [historical quotes](https://docs.alpaca.markets/us/reference/stockquotes-1)
and [quote round-lot size fields](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data).
The 100-share assumption is used only when ask is no greater than $250; other
lot sizes remain unverified and are skipped rather than inferred from profits.
This is a declared diagnostic convention, not certification of every listing.

```sh
python research/martin-luk/run_replay_quote.py --manifest work/mlp2-replay/normalized/manifest.json --output work/mlp2-quotes/observed-5bp --gap-policy OBSERVED_ONLY --adverse-bps 5
python research/martin-luk/audit_quote_history.py --report work/mlp2-quotes/observed-5bp --quotes work/mlp2-quotes/quote-pages
python research/martin-luk/summarize_quote_replay.py --root work/mlp2-quotes --cohort work/mlp1-history/cohort.json --output docs/reports/martin-luk-v2-replay
```

Run primary HALT and the prespecified 10/25-bp cases in the same way before the
summary command. Each case reruns the entire cash account. No observed winning
trade is individually deleted, and selection/stop parameters are unchanged.
The quote audit reconstructs the exact request and raw-response seal for every
buy, independently of the execution implementation. Exits remain OHLC proxies.
