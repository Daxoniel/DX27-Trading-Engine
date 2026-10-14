# Run offline order lifecycle conformance

Use the existing Python 3.11+ installation. No credentials, network or realtime
subscription are needed. All order calls target a local scripted broker.

## Scripted fault cases

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.execution_conformance --output work\p2h-demo
```

Nine scripted cases cover partial cancellation, rejection/expiry, lost submit
reply, not-found submission, lost cancel reply, fill/cancel race, cash mismatch,
budget breach and restart after a remote partial fill. PASS means each expected
outcome occurred; not-found and budget-breach cases deliberately remain paused.
Full unit/integration tests also exercise abrupt process death, stale/conflicting
reports, reservation drift, source seals and journal corruption.

Inspect `acceptance.json` and `report.md`. SQLite files under `cases/` are isolated
simulation state, not Alpaca account data. Existing output directories are
refused. Exit 0 means offline conformance; exit 1 means invalid input/storage or
a failed expected outcome.

## Reuse an old historical Shadow journal

Use a complete flat P1-H journal from the [historical Shadow runner](intraday-recorded-shadow.md):

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.execution_conformance --source-journal work\shadow\q1-intra-1b.sqlite3 --output work\p2h-q1-intra-1b
```

The source journal is verified and read-only. Fixed source fills are split into
partial/final simulated reports; duplicate partial reports must not alter the
ledger. `trace-state/` contains the persistent local order book and scripted
broker. The final modeled cash must match the source within $0.000001, and all
source orders must finish FILLED with no remaining positions.

To reopen the same historical state and verify no repeat submissions, use a new
report directory:

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.execution_conformance --source-journal work\shadow\q1-intra-1b.sqlite3 --state-directory work\p2h-q1-intra-1b\trace-state --output work\p2h-q1-intra-1b-repeat
```

`new_submit_calls` must be zero for a completed matching trace. Changed source,
namespace or initial account requires a different state directory. Keep each
SQLite database and sidecars together; do not remove its lease/rollback files
while a process is running. Another writer on the same state is refused.
Linux uses `.venv/bin/python` in place of the Windows executable.

These checks replay already inspected fills. They do not test strategy feedback
under delayed execution or actual broker fills. The next offline phase adds that
historical decision loop. There is no switch to activate real or paper orders.
