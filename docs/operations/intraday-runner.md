# Operate a supervised historical simulation

Use the existing sealed CSV, config and fixed execution profile. No credentials
or paid realtime access are required. Do not point the runner at live order state.

```bash
python -m dx27.adapters.intraday.runner preflight \
  --input work/recorded-shadow/2025-q1.csv \
  --journal work/runner/q1.sqlite3 --run-directory work/runner/runtime \
  --config examples/intraday/intra-1b-config.json --decision-start 2025-02-01 \
  --profile examples/intraday/p2h2-partial-delayed.json

python -m dx27.adapters.intraday.runner run \
  --input work/recorded-shadow/2025-q1.csv \
  --journal work/runner/q1.sqlite3 --run-directory work/runner/runtime \
  --config examples/intraday/intra-1b-config.json --decision-start 2025-02-01 \
  --profile examples/intraday/p2h2-partial-delayed.json \
  --output work/runner/report
```

Preflight is read-only. `STORAGE_RECOVERY_REQUIRED` (exit 4) identifies an
interrupted SQLite transaction: run the original command to recover under both
exclusive leases before prefix verification. Never delete its rollback journal.
For a credential-free synthetic example, first use
`python -m dx27.adapters.intraday.cli demo --output work/demo` and substitute
`work/demo/synthetic-minute-bars.csv`. Omit the config/decision-start for that
example; RVOL warmup is not present in its two sessions.

While running, use another terminal:

```bash
python -m dx27.adapters.intraday.runner status --run-directory work/runner/runtime
python -m dx27.adapters.intraday.runner stop --run-directory work/runner/runtime
```

A stop response acknowledges the request; poll status until STOPPED. Requests
are checked after a committed/verified frame. SIGINT/SIGTERM use that same
boundary in the CLI where the platform delivers Python signals. Windows process
termination can bypass signal handlers; ownership then releases and status shows
INTERRUPTED. Rerun the original command with exactly the same sealed inputs,
config, profile, journal and run directory. Recovery rebuilds a fresh simulator,
verifies the prefix and appends only new frames. No actual broker is resubmitted.

`--stop-after-minutes N` pauses after N newly committed minute frames in an
attempt. Boundary/session frames are also retained. `--max-restarts N` explicitly
permits up to N transient-storage reconstructions, bounded at three; default zero.
Pause count applies to each reconstruction attempt. Persistent failures stop.

`status --stale-after-seconds 30` is the default freshness limit. STALLED means
the supervisor still owns the lease but is not producing fresh health updates.
Investigate the running worker and storage; do not start a second writer or
manually edit its journal. INTERRUPTED means ownership is gone, so the original
run may be resumed. Health snapshots may lag the last journal commit after a
crash. Failure to persist health never grants success. If a report write fails,
the execution receipt may still identify a complete journal; choose a new report
path and rerun rather than overwriting a partial report directory.

Exit codes: run 0 complete, 2 incomplete, 3 paused/stopped, 1 validation/runtime
failure. Status 0 for normal running/controlled/complete states, 4 for not started,
interrupted, stalled, incomplete or failed. Stop 0 requests a current owner;
1 means no valid request was accepted. Failed CLI responses and health files
contain stable error codes rather than exception text.

Keep `health.json`, `owner.sqlite3`, `stop.json` and the journal for diagnosis.
Do not delete active lease files. Temporary offline simulator directories left
by a killed process are not recovery inputs. Health timestamps are stored in UTC;
use your local timezone when reading them. All outputs remain historical modeled
results; actual orders and algorithm optimization stay disabled.
