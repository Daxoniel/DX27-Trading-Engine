# Matched minute-signal × same-day reentry experiment

The user proposes 1-minute signals and allowing same-day reentry. The
[frozen protocol](minute-reentry-protocol.json) tests four cells on the same
172 sessions (2025-04-28 through December 31), 7,994 candidate stock-days and
$100,000 initial shared cash account. No broker orders are sent.

| Cell | Signal interval | Same-day new attempts |
|---|---|---|
| 5m-single | 5 minutes | One signal attempt/name/session |
| 1m-single | 1 minute | One signal attempt/name/session |
| 5m-reentry | 5 minutes | Fresh setup after flat/terminal order |
| 1m-reentry | 1 minute | Fresh setup after flat/terminal order |

Primary modeled adverse cost is 5 bp/side; all four repeat at the prespecified
25-bp stress level. No threshold grid or selection of a preferred cost case.
The historical period has already been examined; this is not a fresh holdout.

## What remains fixed

Daily candidates, EMA/AVWAP support levels, first-two-hour signal window,
three-bar flush/recovery template, 0.3%–2.5% stop-distance constraints, half-ADR
limit, shared account concentration/open-risk/cash limits, 3R partial and
previous-daily EMA9 exit remain fixed. Limits round upward to an exact decimal
cent in all four cells. No ticker selection, stop widening or extra daily-loss
cap is introduced after observing performance.

Three bars mean a 15-minute structure in a 5-minute signal and a 3-minute
structure in a 1-minute signal. This changes both confirmation speed and stop
lookback geometry; it is not a pure latency-only intervention. Luk's
[first-person account](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons)
supports permitting reentries with caution about repeated losses. It does not
establish that this exact 1-minute template is profitable or is his rulebook.

## Common controls required for a meaningful comparison

All four cells use the same **one-minute execution clock**. A completed signal
becomes available at end+1 second; the first later minute open can attempt entry
using a historical quote at/before that exact instant, never a future aggregate
trade open. Quote age/condition, lot-size support, adverse ask price, displayed
quantity cap, residual cancellation and missing-quote rejection follow the
frozen quote-entry diagnostic. Expiry remains five minutes for both intervals.

All cells use only the last three **actual, contiguous** bars; a missing or
invalid interval resets the window. There is no fabricated flat bar and no
requirement that every earlier minute since market open has a qualifying trade.
The 5-minute control therefore does not reproduce PR81's −9.95% baseline:
execution cadence, local gap recovery, exact-cent arithmetic and causal cash
recognition are common controls, not attributed to the signal/reentry factors.

One-minute source bars cover each candidate's first 125 minutes. Their first
125-minute five-minute aggregates replace the corresponding old opening bars
in every cell, with source comparison counts published. Other held names and
the remainder of the day use the prior frozen five-minute history. Missing
minutes can reflect trade-condition aggregation, not necessarily missing feeds.

Positions entered inside a five-minute bucket use one-minute management through
that bucket's end. Applying the full bucket's pre-entry high/low would be wrong.
Thereafter all cells share five-minute stop-first OHLC management. Each minute
open processes already-known pending orders; at open+1 second, intervals ending
at that open become observable, management runs, and signals are formed. A new
position is never managed by a prefill interval. Daily-exit proxy cash is not
spendable before the opening bar is observable. These exit prices still are
conditional OHLC proxies, not verified bid/depth executions.

## Meaning of reentry

An active position or pending order prevents another entry. Once flat or after
a terminal unfilled/capacity-rejected order, a new attempt requires three bars
whose starts are all at/after that known terminal timestamp. The stopped-out
candle and old signal cannot be reused. Same-day attempts are not arbitrarily
capped; the fixed two-hour window and existing risk/cash limits still apply.

The reentry treatment includes new setups after unfilled attempts, not only
after filled-position stopouts. Reports distinguish these paths, and distinguish
the first purchase after an overnight holding exits from a repeated intraday
purchase. This is one explicit interpretation of allowing reentry, not a test
of every possible discretionary reentry method.

## Reproduce

```sh
python research/martin-luk/capture_minute_factorial.py --manifest work/mlp2-replay/normalized/manifest.json --output work/mlp3
python research/martin-luk/prepare_minute_factorial.py --base work/mlp2-replay/normalized/manifest.json --root work/mlp3
python research/martin-luk/run_minute_factorial.py --manifest work/mlp3/normalized/manifest.json --output work/mlp3
python research/martin-luk/audit_minute_factorial.py --report work/mlp3/1m-reentry-5bp --manifest work/mlp3/normalized/manifest.json --quotes work/mlp3/quote-pages
```

The runner uses [code seals](minute-reentry-code-seal.json), sealed session
inputs, GET-only quotes and independent Decimal quote/account audits. The
additional auditor checks the raw three-bar window, no future observations,
new-bar reset after flat/unfilled orders, attempt sequence, quote entry timing,
no overlapping same-name positions and realized R. Raw quotes, bars and ledgers
remain private. Public results contain aggregate metrics and source seals.

Conditional OBSERVED_ONLY results explicitly record absent held intervals and
stale marks; the four 5-bp strict HALT checks do not publish a terminal return
after a data/accounting halt. Unsupported corporate actions/fractional
entitlements still halt. Fixed cohort/sector and final-source-availability
limitations remain. No new 2026 prices, interest, contributions or taxes.
