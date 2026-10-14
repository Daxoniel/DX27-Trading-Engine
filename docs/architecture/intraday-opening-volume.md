# INTRA-1B — Opening Relative Volume Selection

Opt-in research implementation; no production or paper-order activation.

The opening interval stays 09:30 inclusive to 10:00 exclusive New York time,
using the pinned XNYS calendar and all 30 completed one-minute volumes. At 10:00,
each symbol's current opening sum is divided by the arithmetic mean of the same
opening interval in exactly the preceding `lookback_sessions` scheduled sessions.
Defaults: 20 sessions, select RVOL >= 1.0. These are explicit engineering settings,
not fitted parameters or a replication of the five-minute stocks-in-play paper.

The current session never enters its own denominator. Missing/zero-volume
minutes invalidate an opening; a wholly absent symbol/session retains an invalid
calendar slot. Historical slots are never skipped to find better data. Readiness
requires the full lookback and every historical opening valid. Holidays occupy
no slot; DST and early closes use actual calendar opening times. Historical
openings are frozen at 10:00: a later missing minute does not retroactively alter
them or earlier selection. Existing replay quality gates still quarantine the
symbol when that later missingness becomes known.

Selection is published once per symbol/session and stays fixed for the rest of
the session. It gates bot entry evaluation; feature warmup continues for all
symbols. Existing fills, exits, risk limits, costs, short-signal policy and
lexicographic account allocation are retained. This is a threshold eligibility
filter, not a top-N ranking. No full-day volume or future fill-bar volume is used.

`opening_volume: null` (default) preserves INTRA-1A. Enabling the nested config
produces `task=INTRA-1B` and adds selection.csv with numerator/denominator,
historical date bounds, observed/valid counts, RVOL, threshold and rejection
reason. The CSV/source hashes and config remain in summary.json. RVOL replay
requires declared SIP data or labeled synthetic fixtures; IEX/unknown-feed CSV
is rejected. That feed declaration is source metadata, not independent provider
attestation. Historical availability remains assumed at bar end.

Prefix, missing-history, boundary, independent-symbol, input-order, DST/early-close
and ledger tests verify software causality. They do not validate a complete stock
universe, liquidity, profitability, or real-time feed entitlement. See
[delivery priorities](intraday-delivery-roadmap.md) before P1–P3 activation.
