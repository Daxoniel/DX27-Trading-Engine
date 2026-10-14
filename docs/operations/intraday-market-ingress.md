# Run historical market-event conformance

Convert an existing sealed minute CSV to a labeled historical event trace:

```bash
python -m dx27.adapters.intraday.market_ingress convert \
  --input work/recorded-shadow/2025-q1.csv \
  --output work/market-ingress/q1-events.jsonl
python -m dx27.adapters.intraday.market_ingress inspect \
  --input work/recorded-shadow/2025-q1.csv \
  --events work/market-ingress/q1-events.jsonl
```

Conversion creates a new JSONL and SHA-sealed metadata file. Existing outputs
are refused. Inspection returns COMPLETE_INGRESS or INCOMPLETE_INGRESS and
counts each disposition; it creates no trading journal. Omit `--events` to
inspect the canonical assumption directly. Custom fault traces may omit export
metadata, but their normalized full content and clocks are still sealed into the
run manifest. Declared historical timings are not authenticated live observations.

Use the managed runner with that trace:

```bash
python -m dx27.adapters.intraday.runner preflight \
  --input work/recorded-shadow/2025-q1.csv --events work/market-ingress/q1-events.jsonl \
  --journal work/market-ingress/q1.sqlite3 --run-directory work/market-ingress/runtime \
  --config examples/intraday/intra-1b-config.json --decision-start 2025-02-01 \
  --profile examples/intraday/p2h2-partial-delayed.json
python -m dx27.adapters.intraday.runner run \
  --input work/recorded-shadow/2025-q1.csv --events work/market-ingress/q1-events.jsonl \
  --journal work/market-ingress/q1.sqlite3 --run-directory work/market-ingress/runtime \
  --config examples/intraday/intra-1b-config.json --decision-start 2025-02-01 \
  --profile examples/intraday/p2h2-partial-delayed.json \
  --output work/market-ingress/report
```

Use `--stop-after-minutes 1000` for a controlled pause, then rerun identical
inputs/config/trace without it. Existing completed runs verify the full prefix
and append zero frames. Use new journals/run directories for changed receipts,
connections, revisions, source or config. Event-derived datasets cannot be passed
without their associated gate object. Reports expose event quality and equity
readiness; journal minute batches include newly observable market-event audit.
Runtime status/stop/storage recovery retain the [P2-H3 behavior](intraday-runner.md).

For synthetic CI, generate `work/demo/synthetic-minute-bars.csv` with the existing
`dx27.adapters.intraday.cli demo` command, omit the Q1 config/decision-start, then
convert and run as above. No credentials or paid data are needed.

A recovered connection does not validate earlier missing/late data. Complete
backfill plus a SYNC checkpoint restores only forward admission. Old gaps remain
incomplete, post-cutoff revisions stay quarantined and overall performance is
suppressed. Preflight READY permits diagnostic replay of incomplete data; consult
its separate market_ingress result. Never alter old journal frames to apply a
correction. Use a newly declared trace for corrected historical research.

Converter/inspector exit codes: 0 success/complete, 2 incomplete inspection,
1 invalid input. Managed run: 0 complete, 2 incomplete, 3 paused/stopped,
1 validation/runtime failure. Control clocks allow sub-minute precision; bar
starts and SYNC through boundaries remain minute-aligned. Serialized clocks use
UTC. No command enables actual broker orders.

The fixed exact-end cutoff is an offline conformance convention. Real receipt
latency, bounded watermark/buffering and incremental shadow supervision are
future work; realtime provider access and algorithm optimization remain deferred.
