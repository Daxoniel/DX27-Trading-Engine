# MLP2 candidate coverage diagnostic

This stage corrects source mapping and tests daily candidate coverage. It is
not a portfolio return backtest, strategy approval or a broker-order test.

## Results: 2025-04-28 through 2025-12-31

| Same daily data and cohort | Frozen MLP1 | MLP2 |
|---|---:|---:|
| Candidate stock-days | 17 | 7,994 |
| Unique candidate symbols | 14 | 452 |
| Sessions with candidates | 8 of 172 | 172 of 172 |

All 17 MLP1 candidate stock-days also occur in MLP2. This shows that the old
mapping severely restricted candidate coverage on this dataset. It does not
show that MLP2 has an edge: 7,994 observations include repeated names/dates and
are not independent trades. The three mapping changes were evaluated together;
their individual profitability effects have not been measured.

Of 688,344 cohort stock-sessions, the shared stage records 621,603 common
price/liquidity/ADR failures, 18,807 missing histories and 12,722 invalid
histories; 35,212 stock-sessions enter each scanner. The standalone audit
reconciles every name/session and both scanner totals.

Existing private five-minute cache coverage for the 7,994 MLP2 candidate
stock-days: 6,011 have the expected bar count, 669 have fewer bars, and 1,314
are absent. Of 452 symbols, 322 have a file in the existing cache. A complete
count alone does not prove executable prices or data validity. Missing bars
can represent trading inactivity, halts or data issues and need investigation.

Artifacts: [coverage counts and hashes](coverage.json),
[independent artifact audit](independent-validation.json),
[intraday inventory](intraday-inventory.json), and
[protocol publication](protocol-publication.json).

Protocol and source audit: [mapping-v2.md](../../research/martin-luk/mapping-v2.md).
The rule protocol was published before this diagnostic's full scan. Execution
optimizations did not change scanner rules; the final runner source is hashed
in the result. Preliminary candidate counts were visible during development.
The 2025 period was already examined in MLP1; it is not a fresh holdout.

The comparison uses identical vendor daily OHLCV for both scanners. Its MLP1
column does **not** reproduce the previous report, which used aggregated RTH
bars and required complete five-minute warmup. Do not compare the new MLP2
counts directly to the previous four stock-days as if only strategy changed.

Both versions share the same 4,002-name archived cohort, missing-history
handling, split adjustment and common necessary price/liquidity/ADR filter.
The cohort is not a verified full historical US common-stock universe.
Final revised bars and action records do not establish first availability.
Vendor daily volume includes trades beyond the minute-price update population;
it is not certified RTH-only volume. Daily AVWAP is a typical-price approximation.

Changes remove three unsupported restrictions, rather than optimizing observed
profits: simultaneous same-sector entry setups, mandatory two-level 0.5%
confluence, and the prior-EMA21-touch veto. Candidate levels are alternatives;
the morning recovery and account risk constraints remain unchanged. This does
not implement discretionary base recognition, theme emergence or reentries.

Public artifacts contain counts/hashes, not vendor price histories. Private
daily plans remain outside Git. The standalone audit reconstructs cohort and
summary accounting; it cannot validate vendor truth or profitability.

The next step is a separately frozen execution replay using candidate intraday
data, one shared cash account, corporate actions and independently reconciled
fills. Any missing held-position bars must be disclosed rather than silently
removing trades. A wider watchlist alone is insufficient to start strategy
Paper orders. No orders were sent by this diagnostic.
