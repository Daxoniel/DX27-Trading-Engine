# Operate incremental historical Shadow input

Use an H4 normalized event JSONL and the original sealed CSV context. For a
credential-free demo, generate the existing synthetic CSV then use
`dx27.adapters.intraday.market_ingress convert` as described in
[H4 operations](intraday-market-ingress.md).

```bash
python -m dx27.adapters.intraday.incremental_shadow run \
  --input work/recorded-shadow/2025-q1.csv \
  --events work/market-ingress/q1-events.jsonl \
  --journal work/incremental-shadow/q1.sqlite3 \
  --run-directory work/incremental-shadow/q1-runtime \
  --config examples/intraday/intra-1b-config.json --decision-start 2025-02-01 \
  --profile examples/intraday/p2h2-partial-delayed.json \
  --queue-capacity 16 --output work/incremental-shadow/report
```

Queue capacity defaults to 128 and must be 1–4096. `--max-event-bytes` defaults
to 16,384; limits must be 512–1,048,576 bytes per physical line. Oversized lines
fail before JSON decoding. The bounded queue can process much larger same-clock
bursts without dropping records or advancing the watermark early. Keep these
limits unchanged when resuming the same manifest.

Add `--stop-after-minutes 1000` for a controlled boundary. Rerun without it to
restore the receiver cursor and read only uncommitted deliveries. Strategy and
simulated account reconstruction use already committed minute inputs. The receipt
separates `receiver_events` and source cursor from `events_parsed_this_attempt`:
prefetched events may exceed the committed count before a pause, while a completed
repeat parses zero and appends zero. Queue peak/backpressure figures describe the
current invocation and do not form part of the deterministic minute history.

```bash
python -m dx27.adapters.intraday.incremental_shadow status \
  --run-directory work/incremental-shadow/q1-runtime
python -m dx27.adapters.intraday.incremental_shadow stop \
  --run-directory work/incremental-shadow/q1-runtime
```

Stop requests and CLI SIGINT/SIGTERM are honored after a committed/verified frame,
where the platform delivers Python signals. A request targets the current unique
attempt, so it cannot stop a later resume. Forced termination releases ownership;
status reports INTERRUPTED for a nonterminal record with no owner. Resume the
original inputs/config/profile/queue settings. SQLite rolls back an interrupted
receiver transaction before maps/cursor integrity are checked. Do not edit maps,
checkpoints, frame hashes or hot rollback files to force recovery.

Health records operational phase, last account snapshot, cursor, processed prefix
and parsed-source count. A heartbeat can lag a crash; the journal is authoritative.
A live owner with an old heartbeat is STALLED and never starts a competing worker.
This CLI does not auto-retry source validation or storage failures. Report-write
failure records FAILED separately while preserving the completed execution
receipt; choose a new report path for a retry. Existing report directories are
refused.

The run manifest seals source CSV values/metadata, the raw event-file hash, the
calendar dependency, config, profile and resource bounds. Source mutations,
changed profiles/limits, foreign journals and state/cursor corruption are refused.
Moving an identical source does not authorize different content. Optional event
export metadata is verified when present; unsealed fault traces remain declared
historical inputs, not authenticated realtime observations.

Exit codes: run 0 complete, 2 incomplete, 3 paused/stopped, 1 validation/runtime
failure. Status/stop retain H3 meanings. Failure output uses stable codes without
raw exception text. Reports include the modeled ledger and incremental receipt;
minute frames contain their frozen input, observable audit and receiver checkpoint.
Raw event times and stored clocks use UTC.

This remains an offline historical OHLC simulation with incremental ingestion.
The CSV context and report arrays remain finite-horizon memory inputs. No socket
feed, paid data or actual broker submission is enabled, and no algorithm parameters
are optimized.
