# DX27 Roadmap

## Intraday automation — active direction

- [x] **INTRA-1A implementation / offline conformance** — minute CSV/SIP adapter,
  synchronized ORB baseline, complete opening range, calendar exits, modeled
  costs, account risk and fill/trade/equity ledgers with causal/accounting tests.
  See [architecture](docs/architecture/intraday-replay-ledger.md) and
  [run instructions](docs/operations/intraday-replay.md).
- [x] **INTRA-1A authenticated historical SIP / ledger acceptance** — SPY/QQQ/IWM,
  2025 Q1, 145,553 source minutes, 70,200 regular-session minutes, 60 complete
  sessions; cash/cost/equity reconcile, no unresolved positions. Strategy
  effectiveness and original-cutoff availability remain unverified. See
  [acceptance record](docs/reports/intra-1a-real/validation.md).
- [x] **INTRA-1B — Opening Relative Volume Selection implementation** — opt-in
  30-minute opening volume / preceding 20 scheduled opening means, engineering
  threshold 1.0, causal publication at 10:00 New York, explicit missing/history
  rejection, separate selection ledger. No fitted threshold or effectiveness claim.
- [x] **INTRA-1C — Fixed Paired Historical Comparison** — Q2 2025 protocol
  published before capture, unchanged baseline/RVOL and costs, 62 paired days;
  both arms lose, RVOL-minus-baseline -0.2300 pp and registered block-bootstrap
  interval spans zero. No tuning or effectiveness approval. See the
  [result and exposure record](docs/reports/intra-1c-2025-q2/validation.md).
- [ ] **INTRA-1D — Paper Execution Conformance** — not started; shared decision
  logic, persistent orders/recovery and actual execution-deviation checks.

### Active delivery priorities — P0–P3

- [x] **Framework acceptance consolidation (2026-10-15)** — historical
  engineering path accepted for fixed-rule evaluation; automated paper execution
  remains not ready. Evidence, scope and remaining prerequisites are in the
  [readiness review](docs/reports/intraday-framework-readiness/validation.md).

- [x] **P0 read-only diagnostic code / offline checks** — explicit paper account,
  clock and positions GETs, redacted results, no order path. Historical SIP
  access is verified independently.
- [x] **P0 account connection acceptance** — 2026-10-14 after updating domain
  bindings, all three GET probes succeeded. Account ACTIVE, account/trading
  unblocked, no positions; redacted evidence is committed. Order submission and
  realtime market-data entitlement remain separate gates.
- [ ] **P1 realtime data + Shadow Mode — DEFERRED realtime access** — receive minute bars,
  run the shared ORB/optional RVOL decision logic, persist hypothetical decisions
  and stream quality. Never submit orders. Verify entitlement, late/revised bars,
  calendar boundaries, warmup, reconnect/replay and restart deduplication.
- [x] **P1-H historical recorded Shadow Mode** — user-authorized historical-first
  path; shared INTRA-1A/1B engine, atomic minute journals, deterministic prefix
  recovery and duplicate-free hypothetical records. No credentials/realtime
  subscription required. See [run instructions](docs/operations/intraday-recorded-shadow.md).
- [x] **P2-H1 offline order lifecycle conformance** — durable intents/client IDs,
  partial/rejected/canceled/expired reports, unknown submit/cancel outcomes,
  cumulative Decimal accounting, restart lookup, reservations and exact local
  broker reconciliation. Historical fill traces match modeled cash; no real
  broker path. See [run instructions](docs/operations/intraday-order-lifecycle.md).
- [x] **P2-H2 historical execution feedback loop** — asynchronous simulated
  reports feed actual inventory, sizing, reserved risk, stops and flattening.
  Deterministic journal rebuild, independent cash/equity checks and historical
  acceptance; see [operations](docs/operations/intraday-closed-loop.md).
- [x] **P2-H3 operational runner hardening** — read-only preflight,
  one supervisor per run directory, atomic heartbeats, cooperative stop,
  interrupted/stalled status and bounded offline reconstruction on transient
  storage failures. See [operations](docs/operations/intraday-runner.md).
- [x] **P2-H4 provider-independent historical event ingress** — closed-bar
  envelopes, receipt-cutoff freezing, delivery/bar deduplication, revisions and
  reconnect/SYNC quality gates; feeds shared replay and supervisor. See
  [operations](docs/operations/intraday-market-ingress.md).
- [x] **P2-H5 incremental historical Shadow input** — shared per-event
  policy, durable byte/line/prefix cursors and on-disk deduplication state,
  bounded queues with backpressure, atomic receiver/minute checkpoints;
  restore receiver directly and rebuild strategy from stored minute snapshots.
  See [operations](docs/operations/intraday-incremental-shadow.md).
- [x] **P2-H6 recorded paper adapter contract and disabled execution gateway** —
  normalize broker query/update IDs, reconciliation and admission gates using
  recorded/fake responses before any actual submission. Keep real orders OFF,
  defer paid realtime and continue framework checks before algorithm tuning.
  See [contract and limits](docs/architecture/intraday-paper-contract.md).
- [x] **P2-H7 recorded read-only paper evidence boundary** — recorded transports,
  order/activity lookup pagination, observation coherence and exact execution
  notional/fee aggregation; no actual submission.
  See [supported coverage and limits](docs/architecture/intraday-paper-evidence.md).
- [x] **P2-H8 read-only paper HTTP recorder** — fixed host/GET paths,
  redirects/size limits, redacted errors and explicit incomplete evidence;
  separately validate actual response shapes without enabling execution.
  Actual paper account/clock/positions/orders/activity GET sampling succeeded;
  empty order/activity samples do not verify real fill or fee evidence.
  See [operations and limits](docs/operations/intraday-paper-recorder.md).
- [ ] **P2 automated paper trading** — default order switch OFF, paper endpoint
  only, durable order IDs, partial fills, cancel/reject handling, recovery and
  broker-position reconciliation before enabling automation. Historical simulated
  fills do not establish this capability.
- [ ] **P3 strategy evaluation** — fixed, declared historical comparisons
  (INTRA-1C), shadow decisions and paper fills. Compare net return, drawdown,
  slippage and data quality on untouched periods. INTRA-1B is research preparation;
  Q1 acceptance is not a parameter-selection or profitability approval.
  First INTRA-1C Q2 comparison is complete; Q1 and Q2 are now inspected. Next,
  follow the [literature-driven replication protocol](docs/research/orb-literature/protocol.md)
  before tuning: causal five-minute rule fixtures are implemented and tested
  ([acceptance and limits](docs/research/orb-literature/fixture-implementation.md)); audit sample exposure,
  then register dates, execution semantics, costs and inference before new evaluation.
  The protocol is DESIGN_ONLY, not an executable effectiveness preregistration;
  keep the baseline unchanged and RVOL default OFF meanwhile.

See [the detailed delivery gates](docs/architecture/intraday-delivery-roadmap.md).

## Sentinel — frozen history

Sentinel development is **FROZEN / MAINTENANCE ONLY** after the final
6B-2K-B public-research report integration. The user's next direction is DX27
intraday automated quantitative trading; its implementation is a separate next
task. This roadmap distinguishes working repository state from frozen
architecture and future work:

- **IMPLEMENTED / COMPLETED** — present as working contracts or behavior with
  tests.
- **FROZEN DESIGN** — agreed architecture that is not yet implemented.
- **NEXT** — immediate contract/research or implementation work.
- **DEFERRED** — intentionally outside the current implementation path.

## Frozen design completed

These tasks record completed, frozen Sentinel architecture design. They are not
claims that the corresponding engines are fully implemented.

- [x] **Task 1 — Monitoring Universe** — defines four tiers: `CORE`,
  `CONTEXTUAL`, `DISCOVERY`, and `EXCLUDED_NOISE`. Monitoring is daily-first;
  conceptual 15-minute coverage is limited to Core, holdings, and explicitly
  activated Contextual subjects. Core is intended to contain approximately
  30–40 subjects, Contextual approximately 25–75 with a hard ceiling around
  100, and Discovery approximately 500 liquid US-listed daily candidates.
  Contextual activation and expiry are explicit, Discovery eligibility must be
  reproducible, and missing data is explicit rather than normal. Authoritative
  future inputs may include rates, VIX, breadth, credit spreads, and calendars;
  provider-specific behavior remains outside the frozen domain design.
- [x] **Task 2 — Event Taxonomy** — freezes the nine event primitives
  `PRICE_LEVEL_INTERACTION`, `PRICE_GAP`, `TREND_CHANGE`, `ACTIVITY_ANOMALY`,
  `VOLATILITY_CHANGE`, `RELATIVE_STRENGTH_CHANGE`, `PARTICIPATION_CHANGE`,
  `RELATIONSHIP_CHANGE`, and `SERIES_STATE_CHANGE`. A `DetectedEvent` records
  an observation, not a trade recommendation; its event semantics are
  immutable, with lifecycle states
  `NEW`, `CONTINUING`, `STRENGTHENED`, `WEAKENED`, `RESOLVED`, and `REVERSED`.
  Proxy evidence must be explicit; priority and trading semantics remain
  outside `DetectedEvent`.
- [x] **Task 3 — Priority Model** — freezes the deterministic flow: hard gates,
  semantic deduplication, clustering, bounded ordinal components,
  deterministic predicates, `P0` / `P1` / `P2` / `NOISE`, lexicographic
  ranking, then top-K presentation. It has no weighted aggregate priority
  score; confirmation requires independent evidence lineages, contradictory
  evidence is handled explicitly, and proxy-only evidence is limited. The
  default presentation target is approximately 6 (configurable around 5–7),
  and P0 must never be silently suppressed. The Priority Engine remains future
  implementation.
- [x] **Task 4 — Blind Spot Discovery** — freezes `GROUP_FIRST`,
  `GROUP_AND_MEMBERS`, and `MEMBER_EXCEPTION` observation modes for finding
  unknown outperformers, ETF volume/breadth shifts, cross-asset relationship
  breaks, and macro contradictions. Promotion has dual paths; fast promotion
  requires an approved structured catalyst source. Contextual TTL is 30
  calendar days from the latest material confirmation, unchanged repetition
  does not reset it, and discovery does not permanently expand the universe.
  GPT narrative challenge is optional and interpretive only. The Discovery
  Engine remains future implementation.
- [x] **Task 5 — SentinelReport Contract** — freezes peer **Market Now** and
  **Portfolio Now** sections, plus **Attention Queue** and **Since Last Visit**
  with only durable, currently relevant catch-up information. It requires
  explicit missing-data disclosure, Account Equity, and an Investment
  Performance Index using TWR / unitized NAV semantics, with SPY as the primary
  benchmark and optional QQQ or custom benchmarks. Sentinel Evidence remains
  separate from Analyst Interpretation. The default attention target is
  approximately 6, and P0 cannot be silently suppressed. `SentinelReport`
  remains future implementation.

## Implemented / completed

- [x] **6A-1 Common Foundation** — explicit data status, subjects, observation
  windows, provenance, canonical serialization/hashing, and stable identity.
- [x] **6A-2 Event Foundation** — deterministic `DetectedEvent` contracts and
  the frozen nine-category primitive vocabulary.
- [x] **6A-2 Correctness Hardening** — evidence/lineage membership validation,
  total canonical evidence/provenance ordering, and input-order-independent
  event identity.
- [x] **6A-3 Observation / Universe Foundation** — observation envelopes,
  coverage, universe membership and activation, discovery eligibility, and
  descriptive known-interest snapshots.
- [x] **6B-1 Daily Activity Anomaly Detector** — deterministic, no-lookahead,
  completed-daily-observation detection with explicit availability and
  insufficient-history outcomes.

## Research completed — not production approval

All of these tasks belong to **6B-2**, not Task 7. Completion means the
research or preparation ran successfully, not that a detector passed promotion.

- [x] **6B-2A — Trend Stage-A Research Foundation** — candidate models,
  metrics, selection/OOS split, and tournament framework.
- [x] **6B-2B — Yahoo Real-Data Runner / Validation** — loader, real-data entry
  point, and quality validation.
- [x] **6B-2C — Yahoo OHLC Floating Boundary Hardening** — PR #23.
- [x] **6B-2D — Winner Selection Protocol Pre-registration** — PR #24.
- [x] **6B-2E — Stage-A Real Yahoo Research Run** — frozen `ewmac_64_256`
  winner; `STAGE_A_WEAK_PASS`, research only.
- [x] **6B-2F — Frozen Winner Robustness / Regime Stress Validation** —
  `ROBUSTNESS_FAIL`; four ETFs failed the full-period DC60 floor. EWMAC is
  archived and is not approved as a production detector.

See [the research archive](research/sentinel/6b-2e-6b-2f-ewmac/README.md).

## Current checkpoint

- [x] Preserve frozen EWMAC results, protocols, hashes, and promotion decision.
- [x] Update the architecture to a multi-sensor design and assign the next tasks.
- [ ] **6B-2 — Trend Change + Volatility Change** remains incomplete as a
  production capability. Research completion does not close this parent task.

## 6B-2G checkpoint — design completed and verified

- [x] **6B-2G — Multi-Sensor Contracts & Validation Protocol** — frozen
  19-feed/18-sensor registry, availability and output contracts, simple S/D
  research baselines, causal/prospective evaluation targets and numerical gates,
  and explicit SentinelReport v0.2 design revision. Exact protocol lock and
  offline checks pass; no runtime measurement or market-effectiveness claim.
  See [contracts and validation](docs/architecture/sentinel-sensor-contracts-v1.md).

## 6B-2H checkpoint — implementation conformance

- [x] **6B-2H — Multi-Dimensional Market State Snapshot** — typed scalar and
  OHLCV/availability bridge, pinned XNYS calendar, frozen sensor measurements,
  seven dimension states, resolvable immutable snapshots and MarketNow v0.2
  projection. Synthetic formula/prefix conformance passes; no market-effectiveness
  or live-provider-coverage claim.
  See [runtime and validation](docs/architecture/sentinel-market-state-runtime.md).
- [ ] **6B-2H live operational gate** — verify real provider metadata/bindings,
  actual recorded availability and vintages, and >=95% required-feed coverage.
  Current status: BLOCKED_DATA, real sample count 0 and coverage unknown.
  Fixture completeness is not operational promotion.

## 6B-2I checkpoint — research implementation and source audit

- [x] **6B-2I implementation preparation** — frozen causal S/D research contracts,
  formula/prefix/missing/scenario validation, stable reference library covering
  all 19 feeds and 18 sensors, fixed four-arm logistic experiment and numerical
  primitives. No operational report, Priority, detector, or forecast activation.
  See [research checkpoint](docs/architecture/sentinel-composite-reference-research.md).
- [x] **6B-2I online source probe** — Yahoo SPY/RSP/QQQ/IWM and official Cboe VIX
  downloads succeed; source hashes/first-seen captured. Historical availability
  is unverified; FRED HY history is limited to three years since April 2026.
- [ ] **6B-2I source admission / effectiveness** — BLOCKED_DATA. Admit original-
  cutoff tapes, obtain the required long HY history, and measure age-zero
  reference coverage. No silent lagging, backdating, imputation, or reweighting.
- [ ] **6B-2I fitted-candidate freeze / prospective confirmation** — not started;
  zero sessions, INSUFFICIENT_EVIDENCE. Freeze admitted development coefficients
  and candidate commit before collecting prospective confirmation. A fixture
  PASS cannot complete 6B-2I market validation or open 6B-2J/6B-2K.

## 6B-2I-1 checkpoint — HY OAS source audit

- [x] **6B-2I-1 — HY OAS Source & Availability Audit** — official public FRED
  and ALFRED exports, source definitions, valuation/publication distinction,
  sampled revision comparison and stable reference appendix audited. Repeatable
  capture/offline audit entry points preserve raw source hashes and missingness.
  See [audit and limitations](docs/architecture/sentinel-hy-oas-source-audit.md).
- [ ] **HY admission remains BLOCKED_DATA** — captured history begins 2023-10-09;
  original-cutoff coverage unknown. A 15/16 nominal-date age-zero proxy is not
  operational coverage. Official long-history/field/timestamp/entitlement and
  publication-revision evidence remain unverified.

## 6B-2I-2 checkpoint — recorded capture

- [x] **6B-2I-2 implementation and bootstrap validation** — exclusive-create
  captures, payload/binding seals, stable source profiles, causal replay and
  real 19-feed plus five-metadata-page capture. See
  [recorded capture architecture](docs/architecture/sentinel-recorded-capture.md).
- [x] Separate decision period from per-feed raw history requirements;
  correct the prepared, unsent HY request with explicit old/new hashes.
- [ ] **Source admission remains BLOCKED_DATA** — completed-cutoff operating
  coverage, scalar observation-clock evidence, historical HY publication/revision
  evidence and full reference warmup remain unapproved.

## 6B-2I-3 checkpoint — source clocks and daily coverage pilot

- [x] Freeze 20 consecutive decisions, polling slots, denominator and >=95%
  per-core-feed coverage threshold; preserve the G/I protocols and bibliography.
- [x] Add evidence-backed regular-session VIX bound, provisional Treasury bound
  and isolated v2 source bindings; retain HY/funding conservative windows.
- [x] Validate missed/late/revised inputs, separate daily coverage and original-
  cutoff S/D support, including DST and unsupported early closes.
- [ ] **20-session real coverage pilot** — fixed window 2026-10-08 through
  2026-11-04; reliable deployment NOT_READY. The local worker is best-effort
  fallback only; missing days remain failures. See
  [source clocks and pilot](docs/architecture/sentinel-source-clock-pilot.md).
- [ ] **Source admission remains BLOCKED_DATA** — provisional Treasury/HY clock
  evidence, historical availability and 126/252-session S/D support remain gated.

## Next

- [x] **6B-2K-B — Public Research Report Refresh & Sentinel Freeze** — the
  local report checks FactSet Earnings Insight and four Yardeni charts
  on each page opening, saves each visit independently, and briefly compares
  like-for-like research values with the last saved visit. Forecast-period or
  coverage switches are incomparable, not confirmed trend changes. Missing
  research and price data remain explicit. The browser entry point is local
  HTTP with a Windows launcher; no additional model or trading capability.
  See [scope and architecture](docs/architecture/sentinel-research-live-report.md)
  and [Windows setup](docs/operations/sentinel-research-report.md).
- [ ] **NEXT DIRECTION — Intraday automated quantitative trading** — assess
  the existing trading/backtest/paper-execution foundation in a separate task.
  This report change implements no strategy, broker operation or live execution.

The older Sentinel research tasks below are retained as historical work and
**DEFERRED UNDER THE FREEZE**, with their existing outcomes and incomplete gates.
Only operation of the delivered report and necessary correctness/security/source
compatibility fixes are in scope. Existing pilot collection is not stopped or
reset by this change; no new validation, model tournament or Sentinel expansion
starts automatically.

- [x] **6B-2H-1 — Readable Market Observation Report** — reuse current multi-sensor
  measurements for a real, latest-vintage descriptive report with explicit as-of,
  same-vintage prior comparison, gaps and provenance. No new model, detector,
  forecast or gate promotion. See [report entry point](docs/architecture/sentinel-observation-report.md).
  Latest-attempt failures now block old-value reuse; public examples are synthetic
  only. Withdrawn GitHub object purge remains PENDING_GITHUB_SUPPORT.

- [x] **6B-2K-A — Experimental Forecast Attachment** — explicit user-authorized,
  opt-in Chronos-2 integration: one pinned Apache-2.0 checkpoint, CPU inference,
  five-session ETF and direct relative returns, nominal uncalibrated intervals
  and fixed random-walk comparison. Actual private model run produced all seven
  targets; software and synthetic browser evidence are recorded with the change.
  No fine-tuning or tournament. A separate report attachment leaves
  `market_now.conditional_forecasts` empty and `production_enabled=false`.
  See [experimental forecast scope](docs/architecture/sentinel-experimental-forecast.md).
- [x] **6B-2K-A bounded retrospective diagnostic** — executed 24 fixed
  nonoverlapping rolling origins and 168 valid paired outcomes from latest-vintage
  captures; seven targets compared with the fixed baseline, with mixed results.
  Real outcomes remain private; this is
  not admitted PIT, untouched OOS, prospective confirmation or research PASS.

- [ ] **6B-2I-3A — Durable Pilot Runner & Recovery Validation** — Windows
  reboot recovery and email receipt reported; required logged-out startup,
  forced worker recovery and distinct recovery email evidence pending (NOT_READY);
  final single-writer handoff verified, 102 captures / 353 files unchanged.
  See [acceptance record](research/sentinel/6b-2i-3a-durable-runner/deployment_acceptance.json).
- [x] **6B-2J-A — Change Detection Protocol Pre-registration** — reviewed/merged; parent targets/gates unchanged, two candidates and synthetic plan.
  See [change research](docs/architecture/sentinel-change-research.md).
- [x] **6B-2J-B — Synthetic Implementation & Causal Conformance** — implemented
  and executed for review: 760 trials, zero causal violations; no candidate PASS.
  Historical revisions update later cutoff features/provenance with independent
  as-of oracle checks; original snapshots, decisions and gap eligibility remain fixed.
  15,186 strata insufficient, 14 FAIL; real validation stays BLOCKED_DATA.
  See [synthetic research](docs/architecture/sentinel-change-synthetic.md).
- [ ] **6B-2J-C — Real Development Validation** — BLOCKED_DATA; requires admitted
  PIT evidence and existing S/D research gates, not synthetic or source coverage PASS.
- [ ] Complete the frozen pilot and review each source's actual cutoff coverage;
  resolve provisional source clocks/HY delivery and plan continuous S/D warmup.
  6B-2J real validation remains blocked; protocol/synthetic work may proceed.

## Subsequent 6B-2 tasks — gated sequence

- [ ] **6B-2J — Online Change Detection Validation** — sequential replay of
  trend, volatility, participation, and relationship changes; measure false
  alarms, missed changes, delay, and abstention coverage. Promote only validated
  detectors, using the existing nine event primitives.
- [ ] **6B-2K — Conditional Forecast Research** — separately specify future
  targets and horizons, compare simple baselines, and validate calibration and
  incremental OOS value. Validated operational forecast output stays disabled
  until its own gate passes. The explicitly experimental 6B-2K-A attachment does
  not satisfy or lower that gate.

These tasks follow the [multi-sensor architecture](docs/architecture/sentinel-multi-sensor-design.md).
6B-2G design verification and 6B-2H implementation conformance are complete.
6B-2I collection is active; 6B-2J-A is merged and 6B-2J-B synthetic execution complete. Real 6B-2J validation and
6B-2K remain individually gated; collection and the opt-in 6B-2K-A experiment do
not enable production.

## Planned

- [ ] **6B-3 Relative Strength + Relationship Detection** — remaining production
  integration after 6B-2J; reuse validated relationship work rather than create
  a second research track.
- [ ] **6C Blind Spot Discovery** — implement the frozen Discovery design.
- [ ] **6D Priority Engine** — implement the frozen deterministic, non-weighted
  priority design.
- [ ] **6E SentinelReport** — implement the frozen evidence/report contract.
- [ ] **6F GPT Analyst Layer** — add optional interpretation downstream of
  deterministic Sentinel evidence.

The Monitoring Universe, Blind Spot Discovery, Priority Engine, and
SentinelReport architecture is **FROZEN DESIGN**, not current implementation.
GPT Analyst is future and interpretive, not part of deterministic detection.

## Deferred

- [ ] Execution integration.
- [ ] Broker actions.
- [ ] Autonomous position sizing.
- [ ] Live autonomous trading.

Sentinel remains read-only and frozen. Existing historical replay, simulated
execution, ORB bot, and Yahoo/LEAN adapter work is retained as **EXISTING
CAPABILITY** for the next separately scoped intraday task.


# Historical / Legacy Roadmap

This section preserves the earlier DX27 roadmap for historical context. It is
not the active implementation sequence. Items below may represent completed
prototypes, existing legacy capabilities, superseded plans, or ideas that may
be revisited later. Unchecked boxes here do not make an item an active
**NEXT** task.

The earlier roadmap described DX27 as a modular trading decision system and
required trading logic to remain independent from infrastructure such as LEAN,
market-data providers, broker APIs, and backtesting engines.

# v0.1 — Architecture Foundation

Goal:

Establish stable system boundaries before developing production strategies.

## Repository Architecture

- [x] Create Python-first repository
- [x] Create Core models
- [x] Validate unit-test workflow
- [x] Validate historical market-data access
- [x] Validate DX27 → LEAN signal integration
- [x] Validate end-to-end prototype backtest
- [x] Split code into Intraday / Investment / Strategic domains

## Core Contracts

- [ ] Define MarketDataPort
- [ ] Define ExecutionPort
- [ ] Define PortfolioPort
- [ ] Define IntradayBot contract
- [ ] Define TradeIntent
- [ ] Define StrategyMetadata
- [ ] Define adapter contract tests

## Architecture Rules

- [ ] DX27 Core never imports LEAN
- [ ] Domain logic never imports broker SDKs
- [ ] Runners contain no trading logic
- [ ] Backtest / Paper / Live share the same strategy logic


# v0.2 — Intraday Strategy Platform

Goal:

Create a replaceable and testable short-term trading framework.

## Baseline Strategy

- [ ] Select one mature open-source technical strategy
- [ ] Wrap it through the IntradayBot contract
- [ ] Support native DX27 intraday bots
- [ ] Support external strategy adapters
- [ ] Standardize BotSignal
- [ ] Standardize TradeIntent

## Technical Services

- [ ] Technical feature service
- [ ] Technical rule-pack interface
- [ ] Strategy configuration
- [ ] Strategy version metadata
- [ ] Strategy registry

## Backtesting

- [ ] Build reusable backtest harness
- [ ] Historical-data adapter
- [ ] Record standardized performance metrics
- [ ] Multi-symbol testing
- [ ] Strategy version comparison
- [ ] Regression testing


# v0.3 — DX27 Intraday Strategy Iteration

Goal:

Iteratively add DX27-specific technical knowledge.

- [ ] Technical Rule Pack v1
- [ ] Trend filters
- [ ] Momentum filters
- [ ] Volume filters
- [ ] Volatility filters
- [ ] VWAP research
- [ ] Breakout research
- [ ] Mean-reversion research
- [ ] Compare every version against baseline

## Runtime

- [ ] Paper-trading adapter
- [ ] Paper-trading validation
- [ ] Execution logging
- [ ] Decision explanations
- [ ] Strategy health monitoring


# v0.4 — Investment Domain

Goal:

Implement the DX27 27-rule framework for medium- and long-term investment
decisions.

## DX27 Core 27

### 18 Veto / Risk Rules

- [ ] Define rule schema
- [ ] Implement 18 veto rules
- [ ] Add evidence and explanation output

### 9 Positive Triggers

- [ ] Define trigger schema
- [ ] Implement 9 positive triggers
- [ ] Add evidence and explanation output

## Investment Analysis

- [ ] Technical context
- [ ] Fundamental context
- [ ] Rule evaluation
- [ ] Triggered veto rules
- [ ] Satisfied positive triggers
- [ ] Structured advisory output
- [ ] `dx27 analyze TICKER`


# v0.5 — Strategic Domain

Goal:

Support major portfolio allocation and annual rebalance decisions.

- [ ] Capital Doctrine v1
- [ ] Portfolio context
- [ ] Macro context
- [ ] Sector context
- [ ] DX27 Core 27 integration
- [ ] Doctrine + Core 27 evaluation
- [ ] Annual rebalance engine
- [ ] Strategic allocation output


# v0.6 — Multi-Bot Coordination

Goal:

Coordinate multiple strategies without coupling them together.

- [ ] Coverage / Discovery service
- [ ] Dynamic candidate universe
- [ ] Bot activation
- [ ] Strategy Coordinator
- [ ] Signal conflict handling
- [ ] Risk coordination
- [ ] Capital allocation across bots


# v1.0 — Portable DX27 Platform

- [ ] Multiple Intraday Bots
- [ ] Investment Advisory
- [ ] Strategic Rebalance
- [ ] Historical Backtesting
- [ ] Paper Trading
- [ ] Multiple infrastructure adapters
- [ ] LEAN adapter
- [ ] Alternative engine adapter
- [ ] Simple clone-and-run setup
- [ ] Contributor documentationke
