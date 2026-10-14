# Historical closed-loop runner

Use an existing minute CSV and its source metadata. No credentials are required.

```bash
python -m dx27.adapters.intraday.closed_loop \
  --input work/intra-1a-demo/synthetic-minute-bars.csv \
  --journal work/closed-loop/demo.sqlite3 \
  --profile examples/intraday/p2h2-partial-delayed.json \
  --output work/closed-loop/report
```

Generate the demo first with `python -m dx27.adapters.intraday.cli demo --output
work/intra-1a-demo`. Omit `--profile` for immediate full-fill control. Add
`--config examples/intraday/intra-1b-config.json` for optional RVOL selection.
Historical acceptance also used `--decision-start 2025-02-01` for Q1 warmup.

`--stop-after-minutes 1000` pauses after 1,000 newly committed minute frames.
Rerun without that flag to reconstruct and verify the committed prefix before
continuing. A completed rerun appends zero frames. Keep the same source metadata,
config and profile. Preserve the journal; temporary simulator databases are
rebuild intermediates and must never be reused as a live broker database.

Exit codes: 0 complete, 2 incomplete, 3 paused, 1 invalid input/runtime failure.
Receipts identify prefix verification, append count, chain hash and offline
rebuild. Reports include fills, trades, decisions, equity, sessions and optional
selection CSVs. Incomplete/unknown runs suppress admissible performance metrics.
No command enables actual orders. See [architecture](../architecture/intraday-closed-loop.md)
and [acceptance](../reports/intra-p2-h2/validation.md).
