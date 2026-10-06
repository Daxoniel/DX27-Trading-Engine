# Sentinel Event Taxonomy v0.1

## Scope

This document defines the `DETECT` language in Sentinel's
`SEE -> DETECT -> PRIORITIZE -> REPORT` flow. A detected event is an immutable,
machine-readable record of a material observable change in completed data. It is
not a trade, recommendation, forecast, portfolio target, execution request, or
priority.

The frozen Sentinel Monitoring Universe remains authoritative for observation
scope, cadence, data boundaries, and availability semantics. This taxonomy does
not define P0/P1/P2 priority, blind-spot scoring, reporting policy, or trading
behavior.

## 1. Taxonomy philosophy

Sentinel uses one common `DetectedEvent` model and a small orthogonal vocabulary.
Event types describe the form of an observable change; structured fields carry
its economic meaning. In particular, subjects, economic category, direction,
magnitude, baseline, evidence, relationship metadata, and universe context must
carry information that would otherwise cause event-type proliferation.

The governing rules are:

1. Emit only from completed observations and never use future data.
2. Describe what changed, not what should be done.
3. Prefer an existing event type plus structured attributes over a new type.
4. Keep intrinsic event semantics separate from user relevance.
5. Keep detector confidence separate from importance. v0.1 has no required
   confidence field and no arbitrary decimal confidence.
6. State proxy identity explicitly; never describe a proxy as its underlying
   economic series.
7. Treat detection and reporting as separate concerns. Detection does not imply
   that an event will be surfaced.
8. Preserve deterministic results under historical replay.

## 2. Event families

Families organize the vocabulary but are not separate event classes and need not
be serialized.

### Price and structure

- `PRICE_LEVEL_INTERACTION`
- `PRICE_GAP`
- `TREND_CHANGE`

### Activity and variability

- `ACTIVITY_ANOMALY`
- `VOLATILITY_CHANGE`

### Relative and group behavior

- `RELATIVE_STRENGTH_CHANGE`
- `PARTICIPATION_CHANGE`
- `RELATIONSHIP_CHANGE`

### Normalized series state

- `SERIES_STATE_CHANGE`

Rates, credit, USD, commodities, and volatility-series inputs use the normalized
series family rather than acquiring separate primary event types.

## 3. Final minimal primary event vocabulary

Sentinel v0.1 defines **nine** primary event types:

1. `PRICE_LEVEL_INTERACTION`
2. `PRICE_GAP`
3. `TREND_CHANGE`
4. `ACTIVITY_ANOMALY`
5. `VOLATILITY_CHANGE`
6. `RELATIVE_STRENGTH_CHANGE`
7. `PARTICIPATION_CHANGE`
8. `RELATIONSHIP_CHANGE`
9. `SERIES_STATE_CHANGE`

The vocabulary deliberately consolidates these candidate concepts:

| Candidate concept | Representation |
| --- | --- |
| Breakout / breakdown / support or resistance test | `PRICE_LEVEL_INTERACTION` plus direction and interaction metadata |
| Unusual volume | `ACTIVITY_ANOMALY` with a volume metric |
| Volatility expansion / contraction / regime transition | `VOLATILITY_CHANGE` plus direction and baseline |
| Leadership change | One or more `RELATIVE_STRENGTH_CHANGE` events, potentially composed with participation evidence |
| Breadth divergence | `RELATIONSHIP_CHANGE` between participation and a benchmark |
| Correlation break / cross-asset divergence | `RELATIONSHIP_CHANGE` plus relationship kind |
| Group synchronization | `RELATIONSHIP_CHANGE` plus group-coherence metadata |
| Rate / credit / USD / commodity change | `SERIES_STATE_CHANGE` plus economic category |
| Sector or industry rotation | A later composition of relative-strength, participation, and relationship events |

## Event-type selection precedence

Use the most semantically specific event type available.

The dedicated primitive event types:

- `PRICE_LEVEL_INTERACTION`
- `PRICE_GAP`
- `TREND_CHANGE`
- `ACTIVITY_ANOMALY`
- `VOLATILITY_CHANGE`
- `RELATIVE_STRENGTH_CHANGE`
- `PARTICIPATION_CHANGE`
- `RELATIONSHIP_CHANGE`

take precedence when their semantics apply.

`SERIES_STATE_CHANGE` is the generic primitive for normalized economic or
market-state series when no more specific event type applies.

Examples:

- US 10-year Treasury yield state change
  -> `SERIES_STATE_CHANGE`
- high-yield credit spread deterioration
  -> `SERIES_STATE_CHANGE`
- broad USD state change
  -> `SERIES_STATE_CHANGE`
- realized or implied volatility change
  -> `VOLATILITY_CHANGE`, not `SERIES_STATE_CHANGE`
- a traded ETF crossing a technical level
  -> `PRICE_LEVEL_INTERACTION`
- a traded ETF entering a new deterministic trend state
  -> `TREND_CHANGE`

A proxy instrument may support `SERIES_STATE_CHANGE` only when:

- the event explicitly represents the proxied economic role;
- proxy identity remains explicit;
- the proxy is not mislabeled as the authoritative underlying series.

The same observation must not emit multiple semantically redundant primitive
events solely because more than one taxonomy view could describe it.

Multiple primitive events are allowed only when they represent materially
different measured facts with distinct detector semantics and evidence.

## 4. Common `DetectedEvent` schema proposal

The conceptual model is immutable:

```text
DetectedEvent
├── schema_version
├── event_id
├── detector_id
├── detector_version
├── detector_config_id
├── event_type
├── observed_at
├── observation_window
├── subjects[]
├── economic_category
├── direction
├── magnitude
├── baseline
├── evidence[]
├── semantic_flags[]
├── relationship?
├── universe_context
├── relevance_context
├── data_status
├── deduplication_key
└── provenance
```

### Identity and detector fields

- `schema_version` identifies the event schema contract.
- `event_id` identifies one concrete event occurrence. It should be derived from
  canonical event content so identical replay inputs produce the same ID.
- `detector_id` is the stable identity of the detector definition.
- `detector_version` identifies the detector algorithm's semantics.
- `detector_config_id` identifies the exact effective configuration, including
  thresholds, baseline parameters, permitted session, and required sample sizes.
  It must be a deterministic identifier for a canonical, immutable configuration
  snapshot, not a mutable display name. A content hash is the preferred eventual
  implementation, but its encoding is not frozen here.
- `event_type` is one of the nine primary types.

Changing a threshold or other behaviorally meaningful parameter requires a new
`detector_config_id`, even when `detector_version` is unchanged. Changing the
algorithm or its interpretation requires a new `detector_version` and normally a
new configuration identity as well.

### Time and subject fields

- `observed_at` is when the event first became knowable from completed data, not
  when a report was generated.
- `observation_window` records start, end, timeframe, sample count, and an
  assertion that inputs were complete. Its end cannot exceed `observed_at`.
- `subjects` is a nonempty ordered collection of stable subject references. Each
  reference contains an identifier, symbol or series name, subject kind,
  economic role, and optional `proxy_for` identity. Order is meaningful only
  where roles such as subject and benchmark are directional.
- `economic_category` classifies the observed economic role independently of
  `event_type`, for example broad US equity, technology sector, rates, credit,
  USD, energy commodity, volatility, or market breadth.

### Measurement fields

- `direction` uses a type-constrained controlled value. It describes observed
  movement and never means buy, sell, or hold.
- `magnitude` records the metric, observed value, prior value when applicable,
  absolute or percentage change, normalized value when available, and unit.
- `baseline` records the deterministic comparison method, comparison window,
  sample count, reference value or state, dispersion measure when used, and
  parameters needed to interpret the result.
- `evidence` is a nonempty collection of structured facts supporting detection.
  Each item identifies its metric, subject, value, reference value, unit, window,
  and data status. Human-readable text may supplement but never replace the
  structured facts.

Numerical thresholds belong to versioned detector configuration, not to the
event-type vocabulary. This document does not freeze them.

### Semantic and contextual fields

- `semantic_flags` contains intrinsic descriptors. The v0.1 baseline allows
  `ANOMALOUS`, `DIVERGENT`, and `PROXY_BASED` only when supported by evidence.
- `relationship` is optional for single-subject events and required for
  `RELATIONSHIP_CHANGE`. It records relationship kind, subject roles, expected
  or prior behavior, observed behavior, comparison window, and prior strength.
- `universe_context` records the tier, universe configuration version, and
  membership snapshot needed to reproduce observation scope.
- `relevance_context` records user-specific context separately from semantics:
  `is_holding`, `is_watchlist`, `is_discovered_outside_known_interest`, and an
  optional activation reason.
- `data_status` uses the availability vocabulary from the frozen Monitoring
  Universe. An emitted market event normally requires all mandatory inputs to be
  `AVAILABLE`.
- `deduplication_key` identifies the semantic event stream rather than one
  occurrence.
- `provenance` identifies normalized input models, source-series identifiers,
  last completed input timestamps, and known data or universe revisions. It does
  not authorize provider access from Sentinel logic.

### Confidence policy

`confidence` is intentionally absent from the required v0.1 schema.
Deterministic detectors must not manufacture pseudo-probabilistic decimal values.
A future optional calibrated confidence field would require a defined outcome,
calibration method, and validation evidence. It would still not represent
priority or trading conviction.

### Prohibited fields

`DetectedEvent` must not contain a trade action, buy/sell/hold instruction,
desired position, quantity, notional, target weight, stop or target, order type,
execution instruction, bot activation, strategy parameter change, priority,
recommended response, or expected return.

## 5. Detailed event-type definitions

### `PRICE_LEVEL_INTERACTION`

**Meaning:** A completed price observation materially interacts with an
identified price level or zone. Breakouts, breakdowns, tests, holds, rejections,
and retests are interaction forms, not separate event types.

**Required inputs:** Completed OHLC or closing observations, a level derived
without future data, the preceding state relative to that level, and valid
adjustment/session semantics.

**Minimal detection concept:** Determine whether the subject moved from one side
of a pre-existing level to the other, tested it from either side, or rejected it.
Optional confirmation may use only subsequent completed observations available
at `observed_at`.

**Valid directions:** `CROSS_ABOVE`, `CROSS_BELOW`, `TEST_FROM_ABOVE`,
`TEST_FROM_BELOW`, `REJECT_ABOVE`, `REJECT_BELOW`.

**Required evidence:** Level identity and value or zone, derivation method,
current and preceding relevant prices, interaction kind, timeframe, and completed
timestamps.

**Likely false positives:** Marginal crosses, repeated oscillation, stale or
overfit levels, corporate actions, low-liquidity prints, and unvalidated session
boundaries.

**Universe tiers:** Core, Contextual, and daily Discovery.

**Status:** Active in v0.1 for subjects with valid price semantics.

### `PRICE_GAP`

**Meaning:** A completed session or bar opens materially above or below the
appropriate prior completed close. It remains distinct because discontinuous
session-boundary evidence and corporate-action validation differ from an ordinary
price-level crossing.

**Required inputs:** Current open, prior comparable close, a validated session
boundary, and validated corporate-action and adjustment semantics.

**Minimal detection concept:** Measure current open minus prior comparable close
and normalize against price, range, or volatility under a deterministic
configuration.

**Valid directions:** `UP`, `DOWN`.

**Required evidence:** Current open, prior close, absolute and percentage gap,
normalization baseline, session identifiers, and adjustment status.

**Likely false positives:** Splits, distributions, bad ticks, adjusted versus
unadjusted mismatches, illiquid opening prints, and session mismatch.

**Universe tiers:** Core, Contextual, and eligible daily Discovery assets.

**Status:** Active in v0.1 only for assets whose session, previous-close, and
corporate-action/adjustment semantics have been validated; otherwise
operationally gated.

### `TREND_CHANGE`

**Meaning:** A persistent price-derived trend state changes under a versioned,
deterministic method. It does not forecast continuation.

**Required inputs:** Completed price history, sufficient history for the trend
method, and the prior trend state.

**Minimal detection concept:** Detect a transition among rising, falling, and
neutral states using a configured slope, moving relationship, or equivalent
deterministic method.

**Valid directions:** `UP`, `DOWN`, `NEUTRAL`.

**Required evidence:** Prior and new states, trend metric, comparison window,
sample count, and relevant baseline values.

**Likely false positives:** Whipsaws, range-bound conditions, lag, short samples,
missing observations, and corporate actions.

**Universe tiers:** Core, Contextual, and daily Discovery.

**Status:** Active in v0.1.

### `ACTIVITY_ANOMALY`

**Meaning:** Observed trading activity is statistically unusual relative to an
explicit comparable baseline. In v0.1 this primarily covers volume and traded
value. Volume alone must not be described as market liquidity.

**Required inputs:** A completed activity observation and sufficient comparable
history, including time-of-session comparability for intraday data.

**Minimal detection concept:** Compare the current activity metric with a
configured historical distribution for the same timeframe and, when relevant,
the same intraday interval.

**Valid directions:** `ELEVATED`, `DEPRESSED`.

**Required evidence:** Metric name, observed value, baseline method and value or
distribution, normalized deviation, sample count, timeframe, and session slot.

**Likely false positives:** Open/close seasonality, index rebalances, expiration,
earnings, block trades, corporate actions, and inadequate samples.

**Universe tiers:** Core, Contextual, and daily Discovery.

**Status:** Active in v0.1 for volume and derived traded value. Order-book,
spread, depth, and genuine liquidity measures are postponed until supported.

### `VOLATILITY_CHANGE`

**Meaning:** Realized or implied volatility materially expands, contracts, or
changes configured state. The event makes no bullish or bearish assertion.

**Required inputs:** Completed OHLC/return history for realized volatility, or a
normalized authoritative implied-volatility series or explicitly labeled proxy.

**Minimal detection concept:** Compare a current volatility measure and state
with its historical baseline and preceding state.

**Valid directions:** `EXPANDING`, `CONTRACTING`, `UP`, `DOWN`.

**Required evidence:** Volatility method, realized/implied/proxy classification,
current and prior values or states, lookback, distribution, sample count, and
proxy identity when applicable.

**Likely false positives:** One outlier return, quiet-period comparisons, session
mismatch, short baselines, volatility-product roll effects, and tracking error.

**Universe tiers:** Core and Contextual; daily Discovery for realized volatility.

**Status:** Active in v0.1 for realized volatility from supported prices.
Authoritative implied-volatility operation is gated until a validated series is
available. Proxy-based operation must be labeled.

### `RELATIVE_STRENGTH_CHANGE`

**Meaning:** A subject materially strengthens or weakens relative to an explicit
benchmark or peer reference. This is descriptive relative performance, not an
oscillator name or a recommendation.

**Required inputs:** Completed, time-aligned subject and benchmark observations
with sufficient overlapping history.

**Minimal detection concept:** Detect a configured transition or unusual change
in a relative-return, ratio, or residual series over a declared window.

**Valid directions:** `STRENGTHENING`, `WEAKENING`.

**Required evidence:** Subject and benchmark roles, each return or value, relative
metric, prior state, window, overlap count, and alignment method.

**Likely false positives:** Benchmark selection bias, session or currency
mismatch, stale data, short windows, and corporate-action differences.

**Universe tiers:** Core, Contextual, and daily Discovery.

**Status:** Active in v0.1 and a primary primitive for Discovery.

### `PARTICIPATION_CHANGE`

**Meaning:** Participation in a market or versioned group materially broadens,
narrows, improves, or deteriorates. Disagreement between participation and an
index is represented separately as `RELATIONSHIP_CHANGE`.

**Required inputs:** An authoritative breadth series or stable versioned group
membership, contemporaneous member observations, and explicit missing-member
handling.

**Minimal detection concept:** Compare a participation statistic—such as the
proportion advancing, above a declared trend, contributing positively, or making
new highs/lows—with its prior state or historical baseline.

**Valid directions:** `BROADENING`, `NARROWING`, `IMPROVING`, `DETERIORATING`.

**Required evidence:** Group ID and membership version, eligible/observed/missing
member counts, participation metric, current and reference values, and windows.

**Likely false positives:** Survivorship bias, membership changes, incomplete
constituent data, concentrated weights, small groups, and arbitrary definitions.

**Universe tiers:** Core market structure, Contextual groups, and Discovery
groups.

**Status:** Structurally included in v0.1 but operationally gated until reliable
breadth or versioned group-membership data is available.

### `RELATIONSHIP_CHANGE`

**Meaning:** Behavior among two or more normally related subjects materially
changes. This covers divergence, convergence, correlation break, spread or ratio
dislocation, breadth/index disagreement, cross-asset divergence, and group
synchronization.

**Required inputs:** Completed and time-aligned series, explicit subject roles,
relationship definition, sufficient overlap, and a prior or expected baseline.

**Minimal detection concept:** Compare a current correlation, spread, ratio,
directional agreement, or group dispersion/coherence measure with its configured
historical or predefined expectation.

**Valid directions:** `CONVERGING`, `DIVERGING`, `SYNCHRONIZING`,
`DESYNCHRONIZING`, `STRENGTHENING`, `WEAKENING`.

**Required evidence:** All subjects and roles, relationship kind, expected/prior
behavior, observed behavior, measure and change, window, overlap count, and
alignment method.

**Likely false positives:** Unstable or spurious relationships, incorrect lags,
regime changes, session/timezone or currency mismatch, small samples, and changing
group composition.

**Universe tiers:** Core, Contextual, and Discovery.

**Status:** Active in v0.1 for price-derived relationships with supported,
aligned observations. Relationships requiring unavailable authoritative inputs
remain gated.

### `SERIES_STATE_CHANGE`

**Meaning:** A normalized authoritative economic/market series, or an explicitly
labeled proxy, materially changes level, direction, rate of change, spread, or
configured state. This generic name supports rates, credit, USD, commodities,
and volatility-series inputs without implying that every series is macroeconomic.

**Required inputs:** A normalized authoritative series or explicit proxy,
sufficient history, known unit and observation semantics, and a configured state
or comparison baseline.

**Minimal detection concept:** Detect a material level, trend, acceleration,
spread, or state transition relative to an explicit baseline. The event describes
the observed metric and does not infer a narrative from one series.

**Valid directions:** `UP`, `DOWN`, `STRENGTHENING`, `WEAKENING`, `IMPROVING`,
`DETERIORATING`, and metric-specific values such as `STEEPENING` or `FLATTENING`
when the series itself is a defined curve measure.

**Required evidence:** Series or proxy identity, economic category, metric,
current/prior/reference values, units, baseline, window, rate of change when used,
and explicit proxy declaration.

**Likely false positives:** Proxy tracking or duration effects, commodity roll,
revised or delayed data, incompatible sessions, short-lived dislocations, and
mislabeling a proxy as an underlying series.

**Universe tiers:** Primarily Core and Contextual. Discovery does not invent new
economic series.

**Status:** Active in v0.1 for supported normalized series and explicitly labeled
price proxies. Authoritative rate, credit-spread, canonical VIX, and similar
operations are gated until their frozen future data dependencies exist.

## 6. Observation, anomaly, divergence, and relevance distinctions

Sentinel does not create parallel event systems for these concepts:

| Concept | Representation |
| --- | --- |
| Observation | Every `DetectedEvent` is a material observation. No extra type or flag is needed. |
| Anomaly | `ANOMALOUS` semantic flag plus explicit baseline evidence. Some types, such as `ACTIVITY_ANOMALY`, imply it. |
| Divergence | `RELATIONSHIP_CHANGE` with `DIVERGING` direction and, when useful, the `DIVERGENT` semantic flag. |
| Risk relevance | `relevance_context`, derived without changing intrinsic event semantics. It grants no risk authority. |
| Candidate signal | A separate future downstream artifact that may reference event IDs. It is not a Sentinel event type or `BotSignal`. |

`PORTFOLIO_RELEVANT`, `WATCHLIST_RELEVANT`, and discovery provenance are not
semantic flags. Holding, watchlist, and activation information belongs only in
`relevance_context`.

## 7. Composition examples

Primitive events remain immutable. A later interpretation may reference their
`event_id` values but must not rewrite them.

### Unexpected sector leadership

```text
RELATIVE_STRENGTH_CHANGE (sector vs broad benchmark, STRENGTHENING)
+ ACTIVITY_ANOMALY (sector activity, ELEVATED)
+ PARTICIPATION_CHANGE (versioned sector membership, BROADENING)
-> possible later interpretation: "unexpected sector leadership"
```

There is no `UNEXPECTED_SECTOR_LEADERSHIP` or `SECTOR_ROTATION` primitive.

### Broad market risk deterioration

```text
PRICE_LEVEL_INTERACTION (broad equity subject, CROSS_BELOW)
+ RELATIONSHIP_CHANGE (index vs breadth, DIVERGING)
+ SERIES_STATE_CHANGE (authoritative credit spread, DETERIORATING)
-> possible later interpretation: "broad market risk deterioration"
```

There is no `MARKET_CRASH_WARNING` primitive, and the interpretation itself does
not prescribe action.

### Narrow advance

```text
TREND_CHANGE (capitalization-weighted index, UP)
+ RELATIVE_STRENGTH_CHANGE (equal-weight vs cap-weight, WEAKENING)
+ PARTICIPATION_CHANGE (broad membership, NARROWING)
-> possible later interpretation: "headline advance is concentrating"
```

### Discovery outside known interests

```text
ACTIVITY_ANOMALY (discovery subject, ELEVATED, ANOMALOUS)
+ RELATIVE_STRENGTH_CHANGE (subject vs industry benchmark, STRENGTHENING)
+ RELATIONSHIP_CHANGE (industry members, SYNCHRONIZING)
-> possible later interpretation: "emerging activity outside known interests"
```

The event's relevance context may record
`is_discovered_outside_known_interest=true`; this does not change event semantics
or assign priority.

## 8. Deduplication implications

### Occurrence and stream identity

- `event_id` identifies a single immutable occurrence at a specific completed
  observation.
- `deduplication_key` identifies the semantic event stream that may persist across
  multiple observation cycles.

A deduplication key should normally include:

- event type;
- detector ID and behaviorally relevant detector version;
- detector configuration ID;
- canonical subject identities and directional subject roles;
- relationship kind when applicable;
- economic category;
- direction or interaction kind when it changes semantic identity;
- timeframe and baseline identity;
- stable level ID for price-level interactions.

It must not include report priority, arbitrary prose, portfolio size, watchlist
ordering, or every changing evidence value. Those would fragment one continuing
condition into many streams.

Type-specific rules include:

- Do not emit a new breakout on every bar that remains beyond a level.
- Emit at most one gap stream per subject and validated session boundary.
- Emit a trend event on state transition, not every bar in the same state.
- Use a material-change or configured cooldown rule for continuing activity and
  volatility anomalies.
- Canonicalize relationship subject order except when subject roles are
  directional.
- Never deduplicate a proxy event into an authoritative-series event.

Given identical normalized inputs, universe snapshot, detector version,
configuration, and ordering rules, historical replay must reproduce identical
event IDs, deduplication keys, evidence, and event order.

## 9. Lifecycle treatment

Lifecycle values are not primary event types. The conceptual states are:

- `NEW`
- `CONTINUING`
- `STRENGTHENED`
- `WEAKENED`
- `RESOLVED`
- `REVERSED`

The v0.1 design splits responsibility:

1. A detector emits an immutable occurrence describing the current completed
   observation and semantic stream.
2. A stateful detection coordinator may attach a derived `lifecycle_state` to
   the occurrence by comparing it with the prior occurrence for the same
   `deduplication_key`.
3. Reporting may maintain delivery state and suppress repeated `CONTINUING`
   occurrences, but it must not redefine detection lifecycle.

`NEW`, `STRENGTHENED`, `WEAKENED`, and `REVERSED` can therefore accompany a
market-event occurrence. `RESOLVED` is a lifecycle occurrence referring to a
previous stream, not a tenth market event type. A bare unchanged condition need
not produce a persisted `CONTINUING` occurrence on every cycle; retention policy
is an implementation-design question.

Lifecycle derivation must use deterministic prior state and completed data.
Replay must start from an explicit state boundary so the first occurrence is not
silently classified differently between runs.

## 10. Data-status treatment

The frozen availability states are:

- `AVAILABLE`
- `STALE`
- `INSUFFICIENT_HISTORY`
- `UNSUPPORTED_SESSION`
- `SOURCE_ERROR`
- `UNAVAILABLE`

They are observation and evidence metadata, not ordinary market event types.

Rules:

1. A detector normally emits a market event only when every required input is
   `AVAILABLE`.
2. Stale data must not be treated as current.
3. Insufficient history must prevent detectors that require the missing baseline.
4. Unsupported sessions must prevent invalid gap and cross-asset comparisons.
5. Source errors and unavailable values must never become zeros, unchanged
   values, or normal conclusions.
6. A relationship event requires adequate, overlapping availability for every
   mandatory subject.
7. A source outage affecting many assets must not emit one market event per
   asset. A later reporting layer may aggregate material coverage problems by
   source boundary, tier, category, status, and cycle.

This taxonomy does not define infrastructure telemetry. Data-health aggregation
must remain separate from market-event semantics.

## 11. Proxy treatment

An event based on a proxy must:

- identify the observed proxy as the subject;
- populate the subject's `proxy_for` field;
- include `PROXY_BASED` in `semantic_flags`;
- record proxy limitations in structured provenance or evidence;
- retain the proxy's actual metric and units;
- never claim that the underlying authoritative series was observed.

For example, a Treasury ETF price change may provide rate context, but it is not
an observed US 10-year yield change. A credit ETF relationship is not an observed
option-adjusted spread. A volatility product is not canonical VIX.

Authoritative and proxy events have distinct subject identities and
deduplication keys. When an authoritative input later becomes available, it
supplements or replaces a detector by explicit design revision; it does not
retroactively relabel proxy events.

## 12. Explicitly postponed event types

### Later interpretations, not primitives

- `UNEXPECTED_SECTOR_LEADERSHIP`
- `SECTOR_ROTATION`
- `INDUSTRY_ROTATION`
- `AI_BUBBLE_WARNING`
- `TECH_SELLOFF`
- `MARKET_CRASH_WARNING`
- `RISK_ON`
- `RISK_OFF`
- `CREDIT_STRESS`
- `LIQUIDITY_CRISIS`
- `CONCENTRATION_WARNING`
- `REGIME_SHIFT`
- `SUPPLY_CHAIN_STRESS`
- `SEMICONDUCTOR_RISK_EVENT`

### Concepts represented by existing primitives and attributes

- `BREAKOUT`
- `BREAKDOWN`
- `SUPPORT_TEST`
- `RESISTANCE_TEST`
- `UNUSUAL_VOLUME`
- `VOLATILITY_EXPANSION`
- `VOLATILITY_CONTRACTION`
- `VOLATILITY_REGIME_CHANGE`
- `LEADERSHIP_CHANGE`
- `BREADTH_DIVERGENCE`
- `CORRELATION_BREAK`
- `CROSS_ASSET_DIVERGENCE`
- `GROUP_SYNCHRONIZATION`
- `RATE_CHANGE`
- `CREDIT_CHANGE`
- `USD_CHANGE`
- `COMMODITY_CHANGE`

### Operationally postponed pending data support

- authoritative yield and yield-curve detections;
- real-yield detections;
- authoritative investment-grade/high-yield spread detections;
- full exchange breadth and new-high/new-low detections;
- implied-volatility term-structure detections;
- options skew, positioning, and dealer-exposure detections;
- order-book and market-depth liquidity detections;
- funding-market stress detections;
- local-session international relationship detections;
- macro-release and earnings-surprise detections;
- news-derived and geopolitical classifications.

### Outside Sentinel v0.1

- strategy- or bot-health events;
- execution, order-rejection, or broker-health events;
- infrastructure telemetry events;
- risk-policy or approval decisions;
- portfolio targets;
- trade recommendations and `BotSignal` generation.

## 13. Event-explosion review

Each retained type answers a distinct measurement question:

| Type | Why it remains distinct | Consolidation performed |
| --- | --- | --- |
| `PRICE_LEVEL_INTERACTION` | Requires an explicit, pre-existing price reference and crossing/testing semantics | Breakout, breakdown, tests, rejection, hold, retest |
| `PRICE_GAP` | Requires discontinuity, comparable-close, session, and adjustment validation | Up and down gaps |
| `TREND_CHANGE` | Represents persistent state across a window, not a point interaction | Up, down, and neutral transitions |
| `ACTIVITY_ANOMALY` | Measures activity against a comparable distribution rather than price direction | Volume and traded-value anomalies |
| `VOLATILITY_CHANGE` | Measures variability, which can change independently of direction | Expansion, contraction, implied/realized state changes |
| `RELATIVE_STRENGTH_CHANGE` | Requires an explicit benchmark and is central to Discovery | Strengthening, weakening, and later leadership interpretations |
| `PARTICIPATION_CHANGE` | Measures the distribution across group members rather than pairwise price behavior | Breadth-style participation measures |
| `RELATIONSHIP_CHANGE` | Requires multi-subject expected behavior | Divergence, correlation, spread, ratio, and synchronization changes |
| `SERIES_STATE_CHANGE` | Gives normalized non-price or proxy series strict units/category semantics without one enum per economic variable | Rates, credit, USD, commodities, and volatility-series state |

`PRICE_GAP` cannot safely collapse into `PRICE_LEVEL_INTERACTION` because its
session boundary and adjustment requirements are independently gateable.
`PARTICIPATION_CHANGE` cannot collapse into `RELATIONSHIP_CHANGE` because the
former measures a group distribution even when no second external series exists.
`SERIES_STATE_CHANGE` cannot collapse into `TREND_CHANGE` because it supports
levels, spreads, acceleration, revisions, units, and authoritative/proxy identity
beyond a price trend. No economic category requires its own event type.

Final count: **9 primary event types**.

## 14. Open questions before freeze

1. What canonical subject identifier spans listed instruments, indices, and
   authoritative series without relying on provider-specific symbols?
2. What exact controlled `economic_category` vocabulary is needed for v0.1, and
   how is it versioned against Monitoring Universe roles?
3. Which direction values are global enum members versus type-specific enums?
4. What canonical serialization and hash algorithm will define `event_id` and
   `detector_config_id`?
5. Which detector changes require `detector_version` rather than only a new
   `detector_config_id`?
6. Which configuration inputs must be included in the configuration identity,
   including data/session policies and universe membership versions?
7. Should `lifecycle_state` be persisted on every occurrence or represented in a
   separate immutable lifecycle envelope referencing an event?
8. Does `RESOLVED` require its own occurrence, and how long must prior stream
   state be retained at daily and 15-minute cadences?
9. What deterministic replay boundary initializes lifecycle state?
10. What stable identity and versioning rules apply to derived price levels?
11. What exact previous-close, holiday, early-close, and corporate-action policy
    gates `PRICE_GAP`?
12. Which one deterministic trend method and one robust anomaly-baseline method
    should v0.1 implement first?
13. What minimum sample sizes and missing-data tolerances cause
    `INSUFFICIENT_HISTORY` for each detector?
14. How will 15-minute activity baselines account for intraday seasonality?
15. What authoritative, versioned group-membership source can unlock
    `PARTICIPATION_CHANGE` without survivorship bias?
16. What timestamp alignment, session overlap, currency, and lag policies govern
    `RELATIONSHIP_CHANGE`?
17. Which normalized series and proxies are sufficiently validated to activate
    `SERIES_STATE_CHANGE` in the first implementation?
18. What machine-readable structure records proxy limitations without embedding
    provider-specific behavior in Sentinel?
19. Can any market event use stale optional evidence while every required input
    remains available, or must all attached evidence be `AVAILABLE`?
20. How are revised authoritative series and data vintages represented so replay
    remains reproducible?
21. Must every materially changed continuing condition emit an occurrence, or
    may persistence be reconstructed from state snapshots?
22. How are independent confirming detectors retained without flooding one
    semantic event stream or discarding distinct evidence?
23. What compatibility guarantees apply when new categories, directions,
    evidence metrics, or primary types are added after v0.1?

These questions must be resolved before the taxonomy is marked frozen. They do
not authorize implementation, priority design, or trading behavior.
