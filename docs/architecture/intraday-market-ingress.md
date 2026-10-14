# P2-H4 historical market-event ingress

This checkpoint adds a provider-neutral envelope and a sealed historical trace
compiler. It feeds frozen regular-session minute bars and admission gates into
the existing P2-H2 OHLC execution model and P2-H3 supervisor. ORB, optional RVOL,
cost and risk parameters are unchanged. No socket provider or network order
adapter is implemented. Incremental event processing is the next checkpoint.

```mermaid
flowchart LR
  C[Sealed CSV: universe and calendar] --> F[Receipt-cutoff compiler]
  E[Closed-bar and connection events] --> F
  F --> B[Frozen minute bars]
  F --> G[Readiness timeline and audit]
  B --> R[Existing historical closed loop]
  G --> R
  R --> J[Atomic journal and supervisor health]
```

`MarketEvent` carries event ID, declared source, connection ID, positive delivery
sequence, kind, availability/receipt clocks and optional closed-minute OHLCV,
revision or synchronization boundary. Clocks normalize to UTC; closed bars may
not be declared available before their interval end or received before
availability. OHLCV shares file-input validation. A connection sequence covers
all normalized messages in that connection and starts at one. A provider adapter
must assign/normalize that sequence; it is not an Alpaca-specific sequence claim.

The CSV supplies the declared universe, source and bounded XNYS schedule. Event
bars supply the accepted values; corrected values may differ from the CSV's
historical snapshot. The source calendar horizon is retained even if an entire
final session has no accepted bars. Only regular-session bars are admitted. Canonical conversion
retains source CSV hashes and declares receipt at each minute end as an historical
assumption. It does not establish original availability or realtime entitlement.

The compiler consumes deliveries in receipt order. Clock regression, mixed
sources, out-of-universe/session bars, malformed envelopes, conflicting event
identity and unexplained backward/new sequence reuse fail validation. Exact
receipt-time groups are processed before that clock's freeze. The fixed zero-grace
cutoff is the interval end. A minute's accepted highest version is frozen once;
late/backfilled bars do not replace it or fill historical gaps.

| Delivery condition | Behavior |
| --- | --- |
| Same stable event ID/content, including replay across a connected stream | Deduplicate; no extra bar volume/order |
| Same bar revision/content under another ID | Deduplicate bar |
| Lower revision | Audit stale version; retain highest version |
| Higher revision in the same deadline batch before freeze | Replace candidate atomically |
| Higher revision after cutoff | Retain frozen bar; quarantine symbol |
| Same revision with different OHLCV | Quarantine symbol; remove unfrozen candidate |
| Missing minute / late first bar | Keep gap; pause admission pending synchronization |
| Disconnect, inactive stream or sequence gap | Pause new admission; retain quality evidence |
| CONNECT after outage | Establish new connection, still require SYNC |
| SYNC with complete declared-through raw coverage | Resume forward admission; old frozen gaps remain |

CONNECT IDs identify connection transitions, not heartbeats. Each distinct revision has its own data event ID. Data event IDs stay
stable across reconnect deliveries, while connection and delivery sequence may
change. SYNC must cover expected bars since the interruption and outstanding
gaps, through the current completed-minute boundary; a stale or incomplete claim
does not reopen admission. Post-cutoff corrections/content conflicts remain
quarantined for this trace even after SYNC. An outage or quality fault keeps
historical acceptance incomplete after forward readiness recovers.

The replay checks readiness for bar-end signals and pending entry admission.
Working buy tranches are canceled when their symbol's gate closes, while the
existing reported inventory and order-reconciliation protections remain active.
Protective/calendar exits remain available when modeled prices are present.
Incomplete ingress suppresses overall admissible PnL/drawdown. Audit messages
enter a frame only when their receipt/cutoff clock is at or before its `as_of`.
Post-session corrections appear in the final audit with its later clock.

The execution model retains modeled opens/bar intervals: its historical fill
prices and timestamps are not measurements of network execution at those instants.
This compiler constructs a complete sealed trace before historical replay; it is
not a live streaming loop. P2-H5 will handle incremental closed-bar shadow
processing and bounded buffering before a realtime provider can be connected.

The P2-H4 manifest seals normalized input events, readiness states, audit records,
frozen bar values, source metadata and existing config/calendar. Full-trace changes
produce a new order namespace and are refused on resume. Runtime health timestamps
stay outside that deterministic journal. Canonical economic behavior is compared
with P2-H2; journal bytes/client IDs differ because of the new contract and audit.
