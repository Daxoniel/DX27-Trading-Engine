# P2-H3 managed historical runner

The runner wraps the existing P2-H2 simulation. Signal parameters, execution
profiles and the deterministic journal contract are unchanged. No network
provider or real broker adapter is introduced.

Preflight loads sealed input, validates the shared XNYS session selection,
configuration, source eligibility and path conflicts, and inspects existing
journal metadata and its complete hash chain through a read-only SQLite
snapshot. It checks existing ownership without creating lease files. It reports
missing/zero-volume regular bars as data-quality information; `READY` means the
historical run may start, not that its performance or profitability is admissible.
Invalid source/configuration, incompatible journals and competing writers block
startup. Preflight cannot prove storage will remain writable or guarantee a
future runtime outcome. A hot SQLite rollback journal is reported as
`STORAGE_RECOVERY_REQUIRED` without modifying it. The run command acquires both
supervisor and journal leases, permits SQLite to roll back the interrupted
transaction, and verifies the resulting manifest/chain before simulation.
No trading frames are added during physical storage recovery. Exact semantic prefix verification still occurs inside
the replay engine before new journal records are appended.

A separate SQLite exclusive lease permits one supervisor per run directory.
The P2-H2 journal also retains its independent single-writer lease. Both release
on process exit, including forced termination, on Ubuntu and Windows. PID is
informational; health never signals a PID or assumes it is still the same process.
Input, journal and control-file path aliases are refused. Runtime metadata is
not part of the trading manifest or frame hash, preserving replay equivalence.

`health.json` is replaced atomically after fsync of a temporary file. Progress
is published at phase transitions and at least every two seconds while frames
continue. It includes processed frames, total committed frames, verified prefix,
new append count, last historical time, chain hash and latest reported/oracle
account state. `updated_at` is a wall-clock UTC heartbeat; historical `as_of` is
separate. Health status reflects ownership and heartbeat age:

| State | Meaning |
| --- | --- |
| STARTING | Supervisor acquired ownership and is initializing |
| REBUILDING | A fresh offline simulator is verifying committed history |
| RUNNING | New frames are being committed |
| RECOVERING | An allowed transient storage fault is starting bounded rebuild |
| PAUSED / STOPPED | Controlled boundary; resume through verified replay |
| COMPLETED | Complete closed loop, after any requested report write |
| INCOMPLETE | Data/order/position outcome failed completeness; no automatic retry |
| FAILED | Runtime or report write failed |
| INTERRUPTED | Nonterminal persisted state with no owner, or caught interruption |
| STALLED | Owner still holds the lease but heartbeat is older than the limit |

A heartbeat may lag the journal after a crash. The journal is authoritative;
status never rewrites records or attempts repair. `STALLED` is diagnostic and
never triggers an automatic competing worker. `stop.json` targets a unique
attempt ID; stale requests cannot stop a later invocation. CLI SIGINT/SIGTERM
and explicit requests are honored after a frame has been committed or verified.
Stopping is an offline pause, not an order to liquidate a real account.

Automatic restarts default to zero and may be explicitly limited to at most
three. Only EINTR, EIO and ETIMEDOUT storage exceptions qualify. Each restart
opens a fresh simulator and verifies the committed prefix. Validation,
accounting, corruption, database contention, disk-full and unresolved orders
are not automatically retried. Exceptions are represented by stable error
codes, without raw messages, credentials or environment dumps. Reports are
written after simulation; a report failure preserves the completed journal and
is recorded separately from the execution receipt.

The control hook receives a detached committed-progress envelope, not raw
uncommitted strategy state. A future P2-H4 market-event ingress will separately
address provider availability, revisions, duplicates and reconnect replay.
Historical process supervision is not a live broker recovery guarantee.
