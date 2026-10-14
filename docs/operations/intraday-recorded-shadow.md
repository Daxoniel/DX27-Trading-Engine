# Run historical Shadow Mode

Use Python 3.11+ and the existing installation. This runner is offline; keys and
realtime SIP access are not needed. Keep the historical CSV and its metadata/raw
archive sidecars together. See [the persistence contract](../architecture/intraday-recorded-shadow.md).

## Start and resume on Windows

The earlier Q1 SIP download can be reused without another download:

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.recorded_shadow --input work\intraday-data\2025-q1.csv --journal work\shadow\q1-intra-1b.sqlite3 --config examples\intraday\intra-1b-config.json --decision-start 2025-02-01 --stop-after-minutes 1000
```

Exit 3 means PAUSED after committing 1,000 new minutes. Resume with the same
input, config and journal, omitting the pause option:

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.recorded_shadow --input work\intraday-data\2025-q1.csv --journal work\shadow\q1-intra-1b.sqlite3 --config examples\intraday\intra-1b-config.json --decision-start 2025-02-01 --output work\shadow\q1-intra-1b-report
```

Use `intra-1a-config.json` and a different journal for the unfiltered baseline.
Linux uses `.venv/bin/python`. A process killed during a run can be restarted
with the same command. Keep the `.sqlite3` journal and its sidecars at the same
path; do not delete SQLite rollback files while a process is running. Close the
other process if a journal is busy. Input/config changes require a new journal.

The report contains the usual modeled ledger plus `shadow-receipt.json`.
`verified_prefix_frames` counts checked records from earlier invocations;
`appended_frames` counts new records. Rerunning a completed journal with a new
output directory must append zero. A persisted fill is hypothetical and never
submits an Alpaca order. The report has no realtime or broker acceptance claim.

Exit codes: 0 complete historical shadow; 2 incomplete data/unresolved modeled
positions; 3 controlled pause; 1 invalid input/config/journal/storage.
Incomplete modeled aggregate PnL stays null. Existing report directories are
refused, while existing matching journals are intentionally reusable.

## Synthetic demo without network

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.cli demo --output work\shadow-demo
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.recorded_shadow --input work\shadow-demo\synthetic-minute-bars.csv --journal work\shadow-demo\shadow.sqlite3 --output work\shadow-demo\shadow-report
```

The demo covers a regular session and an early close. Synthetic PnL is software
acceptance only. Real Q1 data has already been inspected and is not an untouched
validation period. Realtime and broker tests can be added later without paying
for them to run this checkpoint.
