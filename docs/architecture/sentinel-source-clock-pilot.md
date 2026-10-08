# 6B-2I-3 — Source Clock Validation & Daily Coverage Pilot

This stage separates observation completion, scheduled publication and actual
availability. Each captured row still uses its actual `first_seen_at`; unknown
row publication timestamps remain null. A schedule never manufactures a vintage.
The frozen G sensor/reference methods and I experiment protocol are unchanged.

## Source clock decisions

| Source | Evidence and interpretation | Prospective profile |
| --- | --- | --- |
| Yahoo ETF daily bars | Actual XNYS session bounds; captured adjusted close and metadata checks retained | Existing session rule in an isolated v2 binding namespace |
| Cboe VIX | Official historical page labels the series daily closing values. The 2021 notice distinguishes final dissemination at 16:15:15 ET from DataShop data extending through 16:16 ET | Conservative regular-session observation completion bound 16:16 New York; not a claimed CSV publication time |
| DGS2 / DGS10 | FRED identifies H.15 and links Treasury methodology. Treasury describes indicative quotations around 15:30, while H.15 has its own release schedule | **Provisional research bound** 16:00 on regular XNYS sessions. The margin is an inference around approximate quotes, not an officially guaranteed exact timestamp; clock admission remains provisional |
| HY OAS | ICE methodology describes underlying valuation clocks; that does not prove the exact BAMLH0A0HYM2 field crosswalk or public FRED delivery | Retain conservative full-day window; exact field/clock and same-day delivery remain unverified |
| SOFR / EFFR | Official New York Fed documentation distinguishes value date, following-business-day publication and potential same-day revisions | Retain full-day value-date window and actual capture availability; no inferred per-row publication stamp |

Enabled regular-session scalar bounds exclude early-close and non-XNYS dates.
They never borrow the equity early-close time for an unverified source calendar.
This limitation counts against coverage; it requires another evidence-backed
profile to change. The pilot happens before the November early close, but tests
cover that case and the different US/European daylight-saving transitions.

New clock documents enter binding validation no earlier than their actual capture.
One raw journal is retained; `profiles/<clock-profile-id>/` isolates new bindings,
coverage and job records. Existing v1 bindings and historical artifacts are not
rewritten. This v2 series starts prospectively; it cannot backdate clock approval.

## Frozen pilot and acceptance

`research/sentinel/6b-2i-3-clock-coverage/pilot_protocol.json` fixes 20 consecutive
XNYS decisions from 2026-10-08 through 2026-11-04, with SHA-256 file locks. No days
can be removed after a failure. Future cutoffs are excluded only until they elapse.
Polling occurs at actual close +20/+60/+100/+115 minutes, with four minutes of
slot grace. A missed slot is journaled as MISSED, rather than backdated or fetched
as a fictitious timely job; later scheduled attempts can genuinely recover data.
Cutoff-elapsed events trigger coverage reporting even when polling has stopped.
HTTP failures, polling/retry counts and late current-day observations are reported
independently from valid source availability at the original cutoff.

The report separates:

- Per-feed availability within the frozen age contract, for all eight core feeds.
- Complete 13-sensor state-vector rate and per-sensor statuses/measurement IDs.
- S's raw age-zero feed availability versus actual complete current S measurements.
- Current D measurement completeness and original-cutoff S/D prior usable counts.

At least 20 completed decisions and >=95% availability for each required feed are
needed for the **coverage pilot** threshold. This small sample measures the pilot
and does not guarantee future reliability. Even a threshold pass does not approve
provisional clocks, historical publication evidence, S/D history or effectiveness.
Frozen S/D require at least 126 prior usable measurements, targeting 252; today's
historical downloads do not substitute for previous original-cutoff measurements.
The overall admission stays BLOCKED_DATA pending separate review.

Revision compaction selects the last available revision separately at each cutoff,
preserving ties and source errors. Each resulting snapshot must equal the complete
uncompacted cutoff-prefix snapshot. Late arrivals can add diagnostic annotations
but cannot rewrite that snapshot. Research outputs have no production events,
priorities, forecasts or fitted-candidate promotion.

## Running and recovery

```bash
python -m dx27.adapters.sentinel.coverage_pilot --store work/task-6b-2i-2/validated-store --daemon
python -m dx27.adapters.sentinel.coverage_pilot --store work/task-6b-2i-2/validated-store --report-only
```

`--capture-now --report-only` performs a genuine diagnostic capture, even outside
a polling slot; this never pretends to be a scheduled after-close attempt.
A file lock prevents concurrent local workers. Job records are exclusive-create
and sealed; immutable coverage archives are content-addressed. Mutable heartbeat
files describe process liveness, not source availability evidence. Raw series and
MarketNow numeric values stay local; checked-in evidence contains hashes/counts.

This managed environment has no usable cron or systemd service. A local worker
can be started here and writes a heartbeat every 20 seconds, but environment
suspension/restart may stop it. It is not a durable scheduler. Resume the same
store and frozen pilot after interruption: missed slots and elapsed days remain
visible, and later captures cannot repair them. The worker stops after the final
pilot cutoff; extending collection needs a separately recorded continuation plan,
keeping the same clock profile and original-cutoff records for S/D warmup.

Reference IDs, URLs, source hashes and interpretation limits are in
`research/sentinel/references/source_clock_pilot_v1.json`. The clock/profile and
pilot lock are frozen separately from the unchanged original bibliography.

## Next gate

Finish the 20-session coverage study, resolve provisional Treasury semantics and
HY field/delivery/history evidence, and accumulate valid S/D historical support.
6B-2J change-detection validation remains gated; this PR starts collection, not
its future effectiveness conclusion.
