# P2-H2 historical execution feedback

`ClosedLoopReplay` inherits the existing minute scheduler, ORB/optional RVOL
signals, indicators, calendar and exits. Both runners use the extracted
`plan_quantity` risk calculation. Strategy parameters remain unchanged.

Each intent passes through the P2-H1 durable order book and independent local
ScriptedBroker. Received cumulative reports update inventory and cash; partial
entries create only the reported quantity. Unfilled buys reserve cash, risk and
position slots. Unknown outcomes pause admission and are queried, never blindly
resubmitted. Pending buys are canceled before protective exits. Lost cancel
replies defer exits until reconciliation, using the then-current open.

The fixed execution profile can delay orders, split quantity, reject entries,
withhold submit/cancel replies and duplicate reports. Delayed fills use future
opens only when that clock time arrives. Current-minute volume is checked after
its close. A 100 bp entry reservation buffer in the example is an execution
budget, not a fitted signal parameter. Prices beyond the budget cancel remaining
quantity. Fees use cumulative quantity so minimum commission is not charged per
fragment. Actual execution time and report reception time are distinct.

The independent broker cash/positions are checked against strategy equity when
reconciled. Unknown intervals make performance inadmissible; oracle drawdown is
reported separately. Realized exit fragments and completed round trips are
separate counters. Orders or positions remaining after the session are explicit
incomplete results; no synthetic last-close fill or premature acknowledgment.

Recovery reconstructs a **fresh offline simulator** from the beginning and
verifies the exact hashed minute/session journal prefix before appending. This
is historical deterministic rebuild, not recovery against a running broker.
P2-H1 separately tests durable order lookup/reconciliation across restart.
Foreign journals and changed inputs/config/profile are refused. Frames include
changed order states and detached execution events.

This remains a whole-share, modeled OHLC simulator. It does not reproduce a
market queue, NBBO or broker service behavior. No network order adapter is used.
Realtime entitlement, real paper automation and algorithm effectiveness remain
separate gates. Next: operational preflight, supervision and event ingress.
