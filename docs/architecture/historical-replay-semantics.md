# Historical Replay Semantics

Phase 1 historical replay uses `America/New_York` as its session timezone.
It filters ordinary weekday regular-trading-session bars to timestamps from
09:30 inclusive through 16:00 exclusive. Bar timestamps are interpreted as the
**start** of their interval.

Each replay step exposes one completed current bar and an immutable history
containing only bars at or before that bar. A signal or trade intent generated
after completed bar **N** is eligible for market execution only at bar **N+1**
open. The simulated execution adapter applies configurable slippage to that
next-open price.

This adapter has no exchange calendar. It does not yet identify holidays or
early-close sessions; those require later calendar infrastructure. Historical
prefixes may include earlier bars for indicator warm-up. Strategy code must
separately define which bars constitute the current session's opening range.
