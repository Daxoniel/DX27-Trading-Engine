# P2-H2 historical closed-loop acceptance

The existing 2025 Q1 SPY/QQQ/IWM historical SIP dataset contains 145,553 source
bars, 70,200 regular-session bars and 60 sessions. Decision activation is
2025-02-01, after January warmup. This period was already inspected; it is not
an untouched strategy evaluation period. Source hash and aggregate receipts are
in [acceptance.json](acceptance.json). Raw data and full journals stay local.

Immediate whole-fill controls match legacy quantities, symbols, sides, reasons,
decision timestamps and execution timestamps. INTRA-1A completes 46 round trips
(92 orders), ending cash 98,293.37199075. INTRA-1B completes 15 round trips
(30 orders), ending cash 99,194.33766854. Differences from legacy final cash are
below 0.000001, reflecting eight-decimal execution accounting.

A fixed INTRA-1B profile delays entries two minutes, exits one minute and fills
half the original quantity per tranche, reserving an additional 100 bp entry
price budget. It completes 15 round trips, 30 exit fragments and 60 fills;
ending cash 99,322.90005194. Cash-flow sums and independent simulator cash agree;
all sessions end flat, with no active orders. This result checks execution
feedback/accounting and does not justify selecting the profile for returns.

Pause after 1,000 minutes commits 1,002 frames including session boundaries.
Resume verifies those 1,002 frames and appends 22,459. Repeat verifies all 23,461
frames and appends zero, with the identical final chain hash. Recovery is fresh
historical reconstruction, never resubmission to an existing broker.

Twenty-two new integration cases cover immediate equivalence, pending cash/risk/
slot budgets, partial-entry protective exits, daily halts, rejection, missing
submit outcomes, lost cancel replies, reception versus execution time, unresolved
closing orders, warmup/missing data, future-price and current-volume causality,
changed manifests, wrong journal types, subprocess death, resume and CLI exports.
The previous lifecycle and recorded Shadow tests remain enabled.

Real orders remain disabled. Realtime data, actual paper execution and strategy
profitability are not verified. Next framework work is P2-H3 operational runner
preflight, supervision, health/recovery reporting and event ingress.
