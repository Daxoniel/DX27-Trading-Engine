# Minute signal and same-day fresh-setup experiment

This is the preregistered matched 2×2 follow-up to [PR81](https://github.com/Daxoniel/DX27-Trading-Engine/pull/81), testing the user’s proposed one-minute signals and same-day reentry. **Historical simulation only; no broker orders.** The previously examined 2025 sample is not independent out-of-sample evidence.

[Protocol and method](../../research/martin-luk/minute-reentry.md) · [Frozen protocol](../../research/martin-luk/minute-reentry-protocol.json) · [Execution code seal](../../research/martin-luk/minute-reentry-code-seal.json) · [Pre-outcome publication receipt](protocol-publication.json)

## Comparison

The four cells share 172 sessions, 2025-04-28–2025-12-31, $100,000 initial cash and 7,994 candidate stock-days. Daily selection/support, risk limits, the three-bar flush/recovery pattern, first-two-hour gate, five-minute expiry and exit rules stay fixed. All four share a one-minute quote-entry clock. The factor changes are signal-bar duration and permission for a fresh same-day attempt after becoming flat or an unfilled order ends.

**The new five-minute control is not the old PR81 baseline.** Common changes include the minute execution clock, local three-bar gap recovery, exact-cent limit rounding, intrabucket management using only post-entry minutes and causal observation/cash timing. Comparing its return with PR81 cannot isolate any one of these changes. Within this experiment, the two factors are compared under matched controls.

Three one-minute bars span three minutes; three five-minute bars span fifteen. This intervention changes stop geometry as well as speed. Reentry requires three fresh contiguous bars starting at/after the previous known terminal event; no reuse of a stopped setup or overlapping same-name positions. Reattempts after an unfilled signal are reported separately from purchases after a previous intraday position closes.

## Results

Results are being generated from the frozen code and sealed inputs. No outcome-based rule changes are permitted.

## Source and execution limits

926,329 raw minute rows were captured in 178 response pages for candidate opening windows. Normalization filters the provider’s inclusive end boundary. All 198,401 derived opening five-minute bars compared with the previous source match in open/high/low/close/volume. Missing minutes are never filled synthetically; missing OHLC bars need not mean no trades occurred.

Entries use the latest regular-condition historical SIP quote no later than the execution instant, no older than 60 seconds, with adverse ask price, displayed-size cap, fixed round-lot support and residual cancellation. Stops, partials and daily exits remain conditional OHLC price proxies, without independent sell-side quote/depth verification. Gap-carry NAV can understate unobserved intraperiod losses. Fixed cohort/security identity, sectors and final-source availability are not certified historical point-in-time inputs.

Raw quotes, prices and trade ledgers stay private. Public artifacts contain aggregate account metrics and hashes: [input manifest](input-manifest.json), [minute-source manifest](minute-source-manifest.json). Hashes and independent accounting checks establish consistency with retained inputs, not vendor authenticity or execution certainty. No fees were purchased, no 2026 holdout prices were fetched, and no orders were sent.

## Reproduce

See the method’s capture/normalize/replay commands, then:

```sh
python research/martin-luk/summarize_minute_factorial.py --root work/mlp3 --manifest work/mlp3/normalized/manifest.json --output docs/reports/martin-luk-minute-reentry
python research/martin-luk/plot_minute_factorial.py --results docs/reports/martin-luk-minute-reentry/results.json --output docs/reports/martin-luk-minute-reentry/equity.svg
```

The summary reruns independent raw-quote/account audits and reconstructs the raw three-bar signal and fresh-window conditions for each entry. The exact one-minute template and fixed exits are DX27 research choices; the sources do not establish that they reproduce Martin Luk’s discretionary decisions.
