# Run INTRA-1C fixed paired comparison

The runner is offline. It cannot download data, select a period, search parameters
or submit orders. It uses the shared replay engine twice, changing only opt-in
opening RVOL. The registered primary metric and paired bootstrap are fixed before
the evaluation data are fetched. See the [protocol](../research/intra-1c/protocol.md)
and [Q2 result](../reports/intra-1c-2025-q2/validation.md).

Use the exact registered Python/dependency versions from
`docs/research/intra-1c/q2-2025-protocol.json`. Other environments must reject the
real study rather than silently change the calendar/statistical implementation.
CI exercises fixtures and the environment-rejection behavior on both platforms;
the actual market study ran in its registered Linux environment.

```sh
python -m dx27.adapters.intraday.paired_comparison \
  --protocol docs/research/intra-1c/q2-2025-protocol.json \
  --protocol-sha256 62731c4e45200b689d099da1acb5b5309d817b9bfe1e35bb5b370343dd266a17 \
  --input work/intra-1c/2025-q2-with-march-warmup.csv \
  --output work/intra-1c/reproduced-comparison
```

Preserve the original CSV and `.raw.jsonl`/`.metadata.json` sidecars. The loader
checks their hashes; the study also checks registered source/feed/adjustment,
request bounds, symbol inventory, calendar-session counts, engine fingerprints,
runtime versions and retrieval start after protocol registration. Metadata is
capture provenance, not proof of original-cutoff availability or global blindness.
A later vendor re-download may contain revisions; retain its distinct hashes and
do not substitute it silently for this study's sealed input.

Outputs are a new directory with unchanged per-arm fill/trade/equity/daily/
decision/quality reports, RVOL selection records, the exact protocol bytes,
paired daily returns and `comparison.json`. Win rate counts strictly positive net
trades and is null when no trade closes. Zero-return evaluation days remain in
both paired arrays. The bootstrap compounds each arm on the same sampled session
indices; it does not independently resample the two portfolios.

Any incomplete/unclosed/nonadmissible arm blocks both primary estimates and the
interval. Session/config/source mismatch or independent accounting failure rejects
the run. Both cash-flow and trade-PnL residuals use absolute tolerance 0.000001.
The shared engine remains responsible for the unchanged causal execution model;
this layer additionally checks minute equity and the daily equity chain.

Exit 0 means the fixed historical comparison completed, 2 means incomplete
comparison reports were written, 1 means rejected protocol/input/output or failed
checks. Existing output directories are rejected. All outcomes keep execution
disabled and never grant strategy-effectiveness approval. Changing a sealed
protocol requires a new explicit registration and exposure record, not editing
the old file after observing results.
