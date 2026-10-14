# P1-H — Historical recorded Shadow Mode

The user chose historical data first on 2026-10-14. Realtime SIP access is deferred;
it does not block this offline checkpoint. This runner consumes a sealed minute
CSV and records the existing INTRA-1A/1B engine's hypothetical decisions, modeled
fills, account marks, RVOL selections and data-quality changes after each minute.
It needs neither credentials nor a market-data subscription.

## Shared engine and time contract

`IntradayLedgerReplay.run(..., observer=...)` keeps all existing strategy,
calendar, risk, allocation and modeled-cost logic. The observer receives detached
record batches after a minute completes and after session finalization. There is
no second strategy implementation. The minute label remains its interval start;
`as_of` is its end. Hypothetical fills at modeled opens remain modeled historical
executions, not orders sent when the batch is received. Historical data is loaded
up front, and the engine's existing causal checks govern use of it.

The historical runner sorts sealed input by timestamp/symbol, rejects duplicate
keys, and checks OHLCV and the CSV/archive seals. It emits every calendar minute,
including missing/zero-volume slots, and uses the same early-close schedule,
warmup and session reset as replay. If optional RVOL is enabled, SIP or clearly
labeled synthetic input is required. The same SIP feed supplies both numerator
and denominator. Historical bar completion is assumed availability; it is not
provider publication time or a realtime receive timestamp.

## Persistence and recovery

Each completed minute/session is one SQLite transaction containing all new
hypothetical decisions/fills/equity/selection records and changed quality records.
A final transaction records the modeled replay summary. Sequence numbers,
unique kind/time keys and a SHA-256 chain make the committed prefix checkable.
SQLite uses full synchronization and rollback journaling. The input manifest
seals actual parsed bars, provenance, full config, calendar package version and
runner contract version. Changed input/config/source/contract requires a new
journal; it cannot revise an existing run.

A separate SQLite exclusive lease prevents another writer from starting on the
same journal and is released when the process exits, including an abrupt exit.
The main database's last transaction survives or rolls back atomically. Recovery
rebuilds the engine from the beginning of the sealed input, checks all prior
frames, then appends only new frames. It does not deserialize mutable engine
state. This makes recovery slower for long histories, but preserves account,
indicator, pending-order and RVOL history without a second state implementation.
Stored frames never trigger external actions. A mismatched reconstructed prefix
or broken chain stops the run. Repeating a completed run appends zero frames.

`--stop-after-minutes` pauses after that many **new** minute transactions, providing
an explicit restart boundary. A pause is not missing-data performance. Run again
with the same CSV/config/journal to continue. A new export directory can be used
when repeating a completed run.

## Checkpoint scope

This completes historical recording/recovery preparation, not full P1 realtime
acceptance or P2 broker execution. It does not handle WebSocket receive order,
late arrivals, revisions, disconnect backfill or broker fills. Source revisions
require a new sealed dataset/run, not mutation of a committed prefix. Broker
submission, partial fills, cancel/reject recovery and account reconciliation
remain separate P2 work; live autonomous trading stays outside this checkpoint.

Tests compare all records with the shared replay, verify prefix causality,
warmup/missing data/early closes, prove restart idempotency, kill a child process
after a committed hypothetical buy, and refuse corruption/config drift and a
second writer. Real Q1 acceptance compares sealed SIP data with prior software
acceptance. Software parity is not evidence of strategy profitability or an
untouched strategy evaluation set.

See [executed real-data and recovery acceptance](../reports/intra-p1-h/validation.md).
