# DX27 Sentinel Roadmap

DX27's active development path is Sentinel-first. This roadmap distinguishes
working repository state from frozen architecture and future work:

- **IMPLEMENTED / COMPLETED** — present as working contracts or behavior with
  tests.
- **FROZEN DESIGN** — agreed architecture that is not yet implemented.
- **NEXT** — immediate implementation work.
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

## Current checkpoint

- [x] Architecture documentation sync after 6B-1.

## Next

- [ ] **6B-2 Trend Change + Volatility Change** — implement `TREND_CHANGE` and
  `VOLATILITY_CHANGE`. Formula, indicator, and threshold selection belongs to
  that research and implementation task; none is selected here.

## Planned

- [ ] **6B-3 Relative Strength + Relationship Detection**.
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

Sentinel remains read-only. Existing historical replay, simulated execution,
ORB bot, and Yahoo/LEAN adapter work is retained as **LEGACY / EXISTING
CAPABILITY**; it is not the active Sentinel development frontier.


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
