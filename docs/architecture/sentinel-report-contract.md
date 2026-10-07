# SentinelReport Contract v0.1

## Scope

This document defines the machine-readable `REPORT` contract for the Sentinel
pipeline:

```text
SEE -> DETECT -> DISCOVER -> PRIORITIZE -> REPORT
```

It specifies how frozen market observations, portfolio/account state,
`DetectedEvent` objects, `DiscoveryCandidate` objects, and `PriorityItem` objects
are projected into a compact report. It does not redesign those upstream
artifacts, implement a user interface, calculate trades, or implement portfolio
performance analytics.

## 1. Report philosophy

The report is an attention contract, not an event dump. It should let a user
understand the current market, current portfolio, immediate material concerns,
and the few most important developments within approximately 30–60 seconds.

The normative ordering is:

1. **Current state first.** Explain what is true now before recounting how it
   developed.
2. **Market and portfolio in parallel.** `MARKET NOW` answers “What is
   happening?” while `PORTFOLIO NOW` answers “What does my exposure look like?”
3. **Attention compression.** Normally show approximately five to seven
   `ReportAttentionItem` objects, without limiting how many `PriorityItem`
   objects may exist upstream.
4. **Discovery visibility without duplication.** Surface important behavior
   outside known interests, but cross-reference an already-visible Attention
   item instead of repeating it.
5. **Secondary catch-up.** `SINCE LAST VISIT` contains only durable historical
   developments that still matter now.
6. **Progressive disclosure.** The collapsed representation is concise;
   deterministic evidence and optional Analyst interpretation can be expanded.
7. **Evidence before interpretation.** Deterministic Sentinel facts remain
   distinct from optional, provenance-aware Analyst output.
8. **Missing means unknown.** Missing or degraded inputs are never rewritten as
   normal, unchanged, neutral, or zero.

The product rule remains:

> Monitor everything important; report almost nothing.

## 2. Report lifecycle and inputs

### 2.1 Inputs

A deterministic report build consumes immutable or versioned snapshots at an
explicit `observation_cutoff`:

- normalized market state and data-status metadata;
- normalized account and portfolio snapshots;
- account-equity and cash-flow records where available;
- cash-flow-adjusted investment-performance series where available;
- configured benchmark series;
- active and recently resolved frozen `DetectedEvent` state;
- active `DiscoveryCandidate` state;
- classified and ranked frozen `PriorityItem` state;
- prior report-development state used for historical aggregation;
- report configuration and schema identity;
- optional `last_seen_at`, used only for catch-up selection.

Optional Analyst enrichment is attached after the deterministic report is
formed. Its absence cannot invalidate or block the report.

### 2.2 Build order

```text
validate input coverage and cutoff
    -> build MarketNow
    -> build PortfolioNow
    -> attach PortfolioPerformance
    -> project ranked PriorityItems into attention items
    -> cross-reference current Discovery candidates
    -> select currently relevant HistoricalDevelopments
    -> apply deterministic visible-capacity and overflow rules
    -> attach report-level data health
    -> compute deterministic report identity
    -> optionally attach separately identified AnalystInterpretations
```

### 2.3 Temporal rules

- Every deterministic fact must be knowable at or before
  `observation_cutoff`.
- `generated_at` records assembly time; it is not the market-observation time.
- Current-state facts are derived identically regardless of `last_seen_at`.
- A later user visit may change only catch-up selection and presentation state,
  not deterministic current facts, priority classes, or evidence.
- Rebuilding with the same effective deterministic inputs and configuration
  produces the same deterministic report body and identity.

## 3. `SentinelReport` top-level contract

### 3.1 Conceptual schema

```text
SentinelReport
├── report_schema_version
├── report_id
├── report_config_id
├── generated_at
├── observation_cutoff
├── reporting_timezone
├── current_state
│   ├── market_now
│   └── portfolio_now
├── portfolio_performance
├── attention
│   ├── visible_items[]
│   ├── overflow_summary
│   └── presentation_state
├── discoveries
│   ├── visible_discoveries[]
│   └── referenced_by_attention[]
├── since_last_visit
│   ├── status
│   ├── effective_last_seen_at?
│   ├── developments[]
│   └── pagination
├── data_health
├── analyst_interpretations[]
└── report_metadata
```

### 3.2 Required versus optional sections

- `current_state`, `attention`, `discoveries`, `data_health`, and
  `report_metadata` are required containers.
- `market_now` and `portfolio_now` remain present even when unavailable; their
  status then explains the missing state.
- `portfolio_performance` remains present with explicit unavailable or partial
  coverage when the required history is missing.
- `since_last_visit` may contain no developments and may omit
  `effective_last_seen_at` when the user has no valid visit state.
- `analyst_interpretations` may be empty without changing report validity.

### 3.3 Typed report concepts

The contract does not collapse all content into one generic item:

- `MarketNow` and `PortfolioNow` are **current-state snapshots**.
- `ReportAttentionItem` is a **projection of a current PriorityItem**.
- `DiscoveryPresentation` is a **projection/reference to a current
  DiscoveryCandidate**.
- `HistoricalDevelopment` is a **durable aggregation of prior state that has
  current relevance**.
- `AnalystInterpretation` is an **optional explanatory attachment**.

These types may share subject and evidence references but retain different
semantics and eligibility rules.

## 4. Current State semantics

### 4.1 Definition

`CurrentState` represents the latest valid state at `observation_cutoff`, not a
chronological narrative. It always contains peer `market_now` and
`portfolio_now` domains.

### 4.2 State-value pattern

Every material state field uses a typed pattern rather than an unqualified
scalar or prose label:

```text
StateValue<T>
├── value?
├── state_as_of
├── data_status
├── source_refs[]
├── evidence_refs[]
├── method_id?
└── qualifiers[]
```

If the required data is unavailable, `value` is absent. It is not set to zero,
`NEUTRAL`, `STABLE`, or `UNCHANGED`.

### 4.3 Derived labels

The report must not invent a regime vocabulary. Labels such as `RISK_ON`,
`NEUTRAL`, or `RISK_OFF` may appear only when a separate deterministic model,
model version, configuration identity, and evidence contract have been approved.
Until then, `MarketNow` exposes component states and relationships without a
synthetic regime label.

## 5. `MarketNow`

### 5.1 Purpose

`MarketNow` summarizes the current market environment from valid normalized
observations. It is not a list of every active event.

### 5.2 Conceptual schema

```text
MarketNow
├── status
├── as_of
├── broad_equity
├── leadership[]
├── participation
├── volatility
├── rates[]
├── credit[]
├── usd_and_macro_series[]
├── major_relationships[]
├── active_structural_conditions[]
├── source_event_ids[]
└── coverage
```

### 5.3 Component semantics

- `broad_equity`: direction/trend/structure for configured broad-market roles.
- `leadership`: current relative leadership by configured market, style, sector,
  industry, or economic role; entries name benchmark and comparison window.
- `participation`: breadth or group participation only where valid membership
  and coverage exist.
- `volatility`: realized or authoritative/proxy implied-volatility state with
  explicit series identity.
- `rates`, `credit`, and `usd_and_macro_series`: normalized authoritative series
  or explicitly identified proxies; a proxy cannot masquerade as its underlying
  series.
- `major_relationships`: currently material cross-asset or internal
  relationships with linked `RELATIONSHIP_CHANGE` evidence where applicable.
- `active_structural_conditions`: current level, trend, activity, or other
  conditions that materially characterize the environment.

Each component records its own status and `as_of`; `MarketNow.status` summarizes
coverage, not market direction.

## 6. `PortfolioNow`

### 6.1 Purpose

`PortfolioNow` describes actual current exposure using normalized portfolio and
account state. It is observational and cannot propose a target portfolio.

### 6.2 Conceptual schema

```text
PortfolioNow
├── status
├── as_of
├── account_equity
├── cash
├── invested_market_value
├── gross_exposure?
├── net_exposure?
├── positions_summary
├── largest_holdings[]
├── concentration[]
├── classified_exposures[]
├── material_risk_observations[]
├── holding_anomalies[]
├── phenomenon_exposures[]
├── snapshot_refs[]
└── coverage
```

### 6.3 Rules

- Values identify currency, timestamp, and valuation coverage.
- `largest_holdings` uses current normalized positions and a deterministic
  ordering; it does not imply approval or recommendation.
- `concentration` states measured exposure concentration and its method; it does
  not declare an unauthorized risk limit breach.
- `classified_exposures` may summarize sector, industry, or theme exposure only
  where classification metadata is available and versioned.
- `material_risk_observations` references current evidence or PriorityItems; it
  does not become a shadow Risk engine.
- `holding_anomalies` references frozen event semantics.
- `phenomenon_exposures` links positions to currently important market or
  Discovery phenomena with explicit relationship provenance.
- Missing portfolio snapshots produce `status=UNAVAILABLE` and coverage detail,
  never an empty portfolio or zero account equity.

## 7. Portfolio performance and benchmark contract

### 7.1 Required separation

The report must expose two distinct economic concepts:

1. **Account equity:** actual account asset value through time, including the
   effects of investment gains/losses, deposits, withdrawals, and other cash
   flows. This is the capital curve and never resets between sessions.
2. **Investment performance index:** a deterministic cash-flow-adjusted series
   representing investment performance without deposit/withdrawal distortion.
   This is the series used for return and benchmark comparison.

Raw account equity must never be compared directly with SPY return.

### 7.2 Conceptual schema

```text
PortfolioPerformance
├── status
├── account_equity_status
├── investment_performance_status
├── benchmark_comparison_status
├── base_currency
├── full_history_start?
├── available_windows[]
├── selected_window
├── account_equity_series
├── investment_performance_series
├── external_cash_flows[]
├── benchmark_comparisons[]
├── method
├── coverage
└── provenance

AccountEquitySeries
├── series_id
├── series_kind = ACCOUNT_EQUITY
├── period
├── observations[] { timestamp, account_value, data_status }
├── currency
└── source_snapshot_refs[]

InvestmentPerformanceSeries
├── series_id
├── series_kind = CASH_FLOW_ADJUSTED_PERFORMANCE
├── period
├── observations[] { timestamp, index_level?, cumulative_return?, data_status }
├── base_value?
├── cash_flow_adjustment_method_id
├── cash_flow_timing_policy_id
└── calculation_provenance

BenchmarkComparison
├── benchmark_id
├── benchmark_role
├── benchmark_series_ref
├── comparison_period
├── portfolio_return
├── benchmark_return
├── excess_return
├── alignment_policy_id
└── coverage
```

### 7.3 Canonical v0.1 performance method

Time-Weighted Return (`TWR`) is the canonical v0.1 investment-performance
measure for benchmark comparison. It is represented conceptually as a unitized
performance index or NAV series that neutralizes external deposits and
withdrawals. The series may be normalized to a start value of `100` and compared
with benchmark series normalized over the identical period.

The authoritative TWR calculation engine, subperiod-linking formula, cash-flow
timing rules, fees, taxes, and valuation treatment belong to Evaluation design
and must be identified by `cash_flow_adjustment_method_id`; Task 5 freezes the
measure and contract semantics but does not implement the calculation.

Regardless of method:

- external deposits and withdrawals are identified separately;
- they affect account equity but are excluded from investment return according
  to the declared method;
- missing or uncertain cash flows degrade or invalidate the adjusted series;
- no interpolated or rounded display value becomes an authoritative input;
- reported precision cannot exceed source/calculation quality.

Money-Weighted Return or IRR may be added later as a supplementary investor-
experience metric. It is not the primary v0.1 benchmark-comparison measure and
must not replace TWR in `investment_performance_series`.

### 7.4 Benchmarks

- `SPY` is the initial primary benchmark role.
- `QQQ`, other configured benchmarks, and future custom benchmarks are supported
  through stable benchmark identities.
- Comparisons use aligned dates, currencies, sessions, and the same period.
- `excess_return = portfolio_return - benchmark_return` only when both inputs
  are valid and aligned.
- Future alpha, beta, up/down capture, and risk-adjusted measures can be attached
  as separately versioned Evaluation outputs; they are not required in v0.1.

### 7.5 Continuous history and display windows

The underlying account and performance histories do not reset. `1M`, `3M`,
`1Y`, and `ALL` are query/display windows over continuous series. `ALL` means
the full available DX27 history and records its actual start and gaps. Changing
`selected_window` changes projection only, never stored history or series
identity.

### 7.6 Availability semantics

Portfolio performance is always addressable in the report. Each of account
equity, investment performance, and benchmark comparison records one of:

- `AVAILABLE`
- `PARTIAL`
- `UNAVAILABLE`

If reliable valuation or external-cash-flow history is absent, the report keeps
the section and states the affected coverage explicitly. For example:

```text
Account Equity: AVAILABLE
Investment Performance: UNAVAILABLE — reliable external-cash-flow history missing
Benchmark Comparison: UNAVAILABLE
```

The report must not fabricate investment returns, compare raw account equity to
SPY, or hide the domain merely because a trustworthy adjusted series cannot be
formed.

## 8. Attention items

### 8.1 Projection, not a new priority model

A `ReportAttentionItem` is a presentation projection of one frozen
`PriorityItem`. It preserves priority, deterministic ranking, clustering,
evidence lineage, and references to constituent events.

### 8.2 Conceptual schema

```text
ReportAttentionItem
├── report_item_id
├── priority_item_id
├── priority_class
├── deterministic_rank
├── display_identity
│   ├── title_key
│   ├── summary_key
│   └── reason_codes[]
├── primary_subjects[]
├── economic_category
├── affected_area
├── scope
├── lifecycle
├── why_surfaced[]
├── portfolio_relevance
├── discovery_relevance
├── evidence
│   ├── constituent_event_ids[]
│   ├── supporting_refs[]
│   └── contrary_refs[]
├── detail
├── analyst_interpretation_ids[]
└── cross_references[]
```

`display_identity` is deterministic and localizable. Free-form GPT prose cannot
participate in `report_item_id`, ranking, priority, or deterministic summary
identity.

### 8.3 Progressive detail

The contract supports three layers:

**Collapsed**

- priority;
- concise deterministic title/summary identity;
- one-line reason code projection;
- affected area;
- portfolio relevance where applicable.

**Expanded deterministic detail**

- Sentinel Evidence;
- why it matters under frozen Priority components;
- affected subjects;
- portfolio relevance/impact context;
- what changed and current lifecycle;
- deterministic watch conditions where already defined.

**Optional Analyst layer**

- interpretation and possible catalyst;
- news/research context;
- alternative hypothesis;
- falsification conditions;
- provenance.

The optional layer is an attachment and cannot rewrite collapsed or expanded
deterministic content.

## 9. Discovery presentation

### 9.1 Purpose

`DiscoveryPresentation` compactly answers whether important behavior is
occurring outside known interests.

```text
DiscoveryPresentation
├── discovery_presentation_id
├── candidate_id
├── candidate_stream_key
├── candidate_state
├── novelty_state
├── canonical_group?
├── primary_subjects[]
├── discovery_families[]
├── known_interest_overlap
├── contextual_promotion_state
├── expiry_or_reevaluation_at?
├── evidence_event_ids[]
├── represented_by_attention_item_id?
└── analyst_interpretation_ids[]
```

### 9.2 Cross-reference rules

- If a visible Attention item already represents the candidate's material
  phenomenon, Discovery records `represented_by_attention_item_id` and does not
  create a second default-visible card.
- If several candidates are constituents of one clustered Attention item, each
  candidate references that item.
- A candidate not represented in Attention may appear compactly when it is new,
  strengthening, newly promoted, materially challenging a narrative, or
  approaching meaningful demotion/expiry.
- Expiry countdown alone is insufficient unless loss of observation scope is
  materially relevant.
- Cross-references use immutable IDs and cannot depend on title-text matching.

Discovery presentation does not change candidate state, Contextual activation,
or priority.

## 10. Since Last Visit and `HistoricalDevelopment`

### 10.1 Purpose

`SinceLastVisit` is a compact, secondary catch-up projection. It is not an event
log or chronological news recap. The user may ignore it without losing the
meaning of `CurrentState`.

### 10.2 Conceptual schema

```text
HistoricalDevelopment
├── development_id
├── development_stream_key
├── first_observed_at
├── material_change_at
├── last_confirmed_at
├── historical_peak_priority
├── current_relevance_state
├── current_relevance_reasons[]
├── subjects[]
├── economic_categories[]
├── linked_event_ids[]
├── linked_priority_item_ids[]
├── linked_candidate_ids[]
├── current_status
├── impact_summary_key
├── evidence_refs[]
├── analyst_interpretation_ids[]
└── expiry_or_resolution?
```

It aggregates and references existing state; it is not a primitive event type or
parallel priority object.

### 10.3 Inclusion predicate

A development is included only when all of the following hold:

1. It materially changed after the effective `last_seen_at`, or it was unseen
   and active during the absence window.
2. It meets at least one durable-development class:
   - former P0;
   - important P1 whose consequences persist;
   - major deterministic market-state change;
   - major portfolio-risk/exposure change;
   - important Discovery theme that persisted;
   - major macro/company development backed by existing events and still
     relevant.
3. `current_relevance_state` is not `EXPIRED` and has at least one structured
   reason explaining why it matters at the report cutoff.
4. Required evidence remains attributable and data quality is adequate for the
   current-relevance claim.

Historical drama alone does not qualify.

### 10.4 Current relevance and expiry

Suggested current-relevance states are:

- `ACTIVE`: the condition remains present;
- `CONSEQUENCES_PERSIST`: the initiating event resolved but a measured effect
  remains;
- `TRANSFORMED`: the development changed form and links to its current state;
- `RESOLVED_RELEVANT`: resolution itself is material and unseen;
- `EXPIRED`: no current consequence justifies catch-up visibility.

An `EXPIRED` development is omitted from default catch-up. A newly qualifying
`RESOLVED_RELEVANT` development normally appears once, then leaves catch-up
eligibility according to deterministic presentation state; manual acknowledgment
is not required. It may surface again only after a material new state change,
transformation, renewed consequence, or re-escalation. `ACTIVE` and
`CONSEQUENCES_PERSIST` developments may remain eligible while their structured
current-relevance predicates continue to hold. Repetition without material
change does not generate another development card.

### 10.5 Ordering and pagination

Developments are ordered deterministically by current relevance class, lasting
materiality, latest material change, historical peak priority, and canonical
`development_id`. They may be projected as pageable/swipeable cards. Pagination
does not affect `CurrentState` or Attention ordering.

## 11. `last_seen_at` semantics

`last_seen_at` belongs to user presentation state, not market truth.

- It affects only the catch-up interval, unseen/resolved marker state, and
  historical pagination.
- It cannot change `MarketNow`, `PortfolioNow`, performance history,
  `ReportAttentionItem` priority, deterministic Discovery state, or data health.
- Invalid or future values are ignored and disclosed in report metadata.
- With no valid value, current state, Attention, Discovery, and available
  portfolio performance still render normally. `SinceLastVisit` reports an
  explicit `UNAVAILABLE` or `NOT_ESTABLISHED` catch-up state and contains no
  fabricated retrospective window.
- The report must not substitute seven days, 30 days, account creation, or any
  arbitrary recent interval for a missing `last_seen_at`. A future `Recent
  Context` feature would be a separate concept, not `SinceLastVisit`.
- Updating last-seen state occurs outside deterministic report content and must
  not mutate historical facts.

Two users with identical deterministic inputs at the same cutoff receive the
same current facts even when their catch-up sections differ.

## 12. Sentinel Evidence versus Analyst Interpretation

The report preserves two explicitly labeled evidence layers.

### 12.1 Sentinel Evidence

- deterministic and structured;
- derived from normalized state and frozen Sentinel contracts;
- references events, candidates, priority items, measurements, configuration,
  and provenance;
- forms the deterministic report identity and remains valid without GPT.

### 12.2 Analyst Interpretation

- optional, explanatory, and separately versioned;
- may research likely catalysts, causal chains, company/group relationships,
  alternatives, thesis challenges, falsification conditions, and relevant news;
- must cite structured Sentinel evidence and external source provenance;
- cannot mutate evidence, establish deterministic priority, activate Contextual
  monitoring, or authorize execution;
- must be visibly distinguishable from Sentinel Evidence in every projection.

An interpretation can be replaced or removed without changing the deterministic
report body or `report_id`.

## 13. Analyst enrichment contract

### 13.1 Conceptual schema

```text
AnalystInterpretation
├── interpretation_id
├── interpretation_schema_version
├── analyst_model_id
├── analyst_config_id
├── generated_at
├── observation_cutoff
├── related_report_object_type
├── related_report_object_id
├── sentinel_evidence_refs[]
├── external_source_refs[]
├── possible_catalysts[]
├── interpretation
├── evidence_chain[]
├── alternative_explanations[]
├── hypothesis_challenge?
├── falsification_conditions[]
├── limitations[]
└── provenance
```

### 13.2 Attachment rules

- `related_report_object_type/id` targets an existing current-state component,
  Attention item, Discovery presentation, or Historical development.
- `sentinel_evidence_refs` are immutable and attributable.
- External claims identify source, publication/event time, retrieval time, and
  revision/verification status where available.
- Model and prompt/configuration identity are explicit.
- Analyst output is not included in deterministic hashing, qualification,
  ordering, or overflow selection.
- Failure, timeout, or absence produces an empty attachment list and optional
  enrichment-status metadata, never report failure.

## 14. Data health

### 14.1 Conceptual schema

```text
ReportDataHealth
├── overall_status
├── generated_at
├── coverage_by_domain[]
│   ├── domain
│   ├── required_count
│   ├── available_count
│   ├── status_counts
│   ├── material_gaps[]
│   └── impact
├── affected_report_paths[]
├── source_conditions[]
└── qualifiers[]
```

### 14.2 Status and impact

Domain observations retain the frozen states:

- `AVAILABLE`
- `STALE`
- `INSUFFICIENT_HISTORY`
- `UNSUPPORTED_SESSION`
- `SOURCE_ERROR`
- `UNAVAILABLE`

Report-level `overall_status` describes coverage only, using a separately
defined finite vocabulary such as `COMPLETE`, `DEGRADED`, or `UNAVAILABLE`; it
must not imply market direction.

Each material gap states its impact, for example:

- breadth unavailable, so participation state is not evaluable;
- stale credit series, so current credit/equity relationships are withheld;
- unsupported macro series, so the relevant component is absent;
- insufficient performance history, so a selected window is unavailable;
- portfolio snapshot unavailable, so `PortfolioNow` is unknown;
- benchmark gap, so excess return is not computed.

One source outage should be aggregated by domain/source rather than emitted as
hundreds of market events. Available sections continue rendering with explicit
qualifiers.

## 15. Report identity and reproducibility

### 15.1 Identities

- `report_schema_version` versions field semantics and compatibility.
- `report_config_id` is a deterministic digest of the effective report
  configuration.
- `report_id` is a deterministic digest of canonical deterministic report
  inputs/content, excluding `generated_at`, user presentation state, and Analyst
  output where those do not affect deterministic content.

The configuration identity covers at least:

- current-state component mappings and summary methods;
- attention visible-capacity policy;
- overflow, dominance, and cross-reference projection rules;
- Discovery visibility predicates;
- HistoricalDevelopment inclusion, relevance, expiry, and ordering rules;
- benchmark roles and performance projection policy;
- data-health aggregation and materiality rules;
- canonical serialization and ID semantics.

### 15.2 Determinism

Given identical normalized market state, portfolio/account state, frozen event,
Discovery, and Priority state, report configuration, prior deterministic
development state, and observation cutoff, the deterministic report body is
identical.

`last_seen_at` may produce a separately identifiable catch-up projection but
cannot change current deterministic content. Analyst interpretation has its own
schema/model/config identities and is not part of deterministic `report_id`.

Canonical serialization defines ordering, timezones, precision, missing values,
set normalization, and hashes. Prose generation, locale, iteration order,
randomness, and LLM output cannot affect deterministic identity.

## 16. Suppression, overflow, and pagination

### 16.1 Visible attention capacity

The frozen initial setting is:

```text
default_visible_attention_capacity = 6
```

The presentation contract may configure a visible capacity from five through
seven items for a particular UI context. Capacity is a report-presentation
setting only: it cannot alter `PriorityItem` creation, priority classification,
or deterministic ranking.

Selection starts from Task 3's deterministically ranked and clustered
`PriorityItem` objects:

1. project all P0 items;
2. fill remaining default-visible slots with ranked P1 then P2 items according
   to the frozen ranking;
3. reuse frozen dominance/clustering semantics so near-identical phenomena do
   not consume multiple cards;
4. do not impose an aesthetic sector quota or artificial diversity rule;
5. retain every nonvisible eligible item in deterministic overflow metadata or
   pagination.

### 16.2 P0 overflow

P0 is never silently discarded. Related raw critical observations should
already be aggregated into coherent `PriorityItem` phenomena by Task 3. If
distinct P0 items still exceed visible capacity:

- all P0 items remain addressable;
- the default report exposes the critical count and overflow condition;
- pagination or “show all critical” access is supported;
- no P0 is demoted to fit the visual cap;
- P1/P2 yield visible capacity before any P0 is hidden behind ordinary
  pagination.

The final UI is outside this contract, but silent truncation is prohibited.
The visible-capacity setting never overrides these P0 overflow rules.

### 16.3 Overflow summary

```text
AttentionOverflowSummary
├── total_priority_items
├── visible_count
├── hidden_count
├── hidden_by_priority
├── p0_overflow_count
├── dominance_suppressed_count
├── next_page_token?
└── deterministic_order_ref
```

“Suppressed” here means not default-visible. It does not rewrite an upstream
priority class to `NOISE`.

## 17. Worked examples

### 17.1 Daily user with only two meaningful P1 items

- `MarketNow`, `PortfolioNow`, and performance remain visible.
- Both P1 items are shown; the report does not manufacture P2 filler to reach
  five cards.
- Overflow counts are zero and catch-up may be empty.

### 17.2 User returns after one month

- Current market and portfolio state appear first and are identical to a daily
  user's current deterministic state at the same cutoff.
- `SinceLastVisit` separately includes only durable developments from the month
  that still matter.
- The section is not a chronological list of every event.

### 17.3 Account grows because of a cash deposit

- `AccountEquitySeries` rises by the deposit amount.
- The external cash flow is recorded explicitly.
- The declared cash-flow-adjusted performance index does not treat the deposit
  as investment gain.

### 17.4 Account equity rises while portfolio underperforms SPY

- Account value may be higher due to positive return, deposits, or both.
- Same-period adjusted portfolio return is compared with SPY return.
- Negative excess return is reported even though raw account equity increased.

### 17.5 Portfolio beats SPY but behaves like high-beta QQQ

- SPY remains the primary benchmark and shows positive excess return.
- A configured QQQ comparison may show closer behavior or smaller excess.
- The report does not claim beta without an approved Evaluation metric; future
  beta/risk-adjusted outputs attach separately.

### 17.6 Seven visible items and additional P2 items

- The configured visible capacity shows the seven highest eligible items.
- Additional P2 items remain in overflow with count, priority distribution, and
  deterministic ordering.
- Their upstream classification is unchanged.

### 17.7 Three related semiconductor events

- Task 3 supplies one clustered semiconductor `PriorityItem` with constituent
  event references.
- REPORT renders one coherent Attention card with expandable evidence, not
  three redundant cards.

### 17.8 New utility Discovery candidate with no holdings

- Discovery shows the candidate because it is new/strengthening outside known
  interests.
- If it is already represented by a P1 Attention item, Discovery links to that
  item rather than adding a duplicate card.
- No portfolio holding or recommendation is implied.

### 17.9 AI thesis challenged by electrical-infrastructure leadership

- Sentinel Evidence shows relative leadership, participation, coherence, and
  relationship facts.
- Optional Analyst Interpretation may explain leadership broadening, an
  alternative explanation, and falsification conditions.
- Interpretation is visibly separate and cannot change priority or activate
  monitoring.

### 17.10 Historical Fed repricing remains relevant

- The initiating event occurred weeks ago, but the rate state and measured
  portfolio/market consequences persist.
- A `HistoricalDevelopment` appears with
  `current_relevance_state=CONSEQUENCES_PERSIST` and current evidence.
- Current rate state still appears independently in `MarketNow`.

### 17.11 Old dramatic event no longer matters

- Its evidence and audit history remain stored.
- With no active consequence or relevant resolution, its development state is
  `EXPIRED` and it is omitted from default catch-up.

### 17.12 GPT Analyst unavailable

- `analyst_interpretations` is empty and enrichment status may note
  unavailability.
- Market, portfolio, performance, Attention, Discovery, catch-up, and health
  render normally from deterministic inputs.

### 17.13 Credit data is stale

- `MarketNow.credit` has no asserted current value and records `STALE`.
- Relationships requiring current credit are withheld or qualified.
- `data_health` reports the material gap; it does not label credit stable.

### 17.14 P0 overflow

- Eight distinct clustered P0 phenomena exist with a configured capacity of
  seven.
- The report exposes all eight as critical through default/overflow access,
  reports `p0_overflow_count=1`, and shows no P1/P2 ahead of the hidden P0.
- No P0 is downgraded or silently removed.

### 17.15 Large holding issue and broad market stress

- Two materially distinct PriorityItems remain: one direct holding-specific
  phenomenon and one broad-market/cross-asset phenomenon.
- Both may appear in Attention; `PortfolioNow` also references the holding risk,
  while `MarketNow` describes broad stress.
- Cross-references prevent duplicated evidence from becoming extra cards.

## 18. Explicit exclusions

Task 5 does not define or implement:

- frontend layout, React components, CSS, interactions, or chart rendering;
- trading actions, recommendations, `BotSignal`, targets, orders, or execution;
- portfolio construction, risk authorization, or approval behavior;
- a new event taxonomy, Discovery algorithm, or Priority model;
- LLM-based deterministic facts, candidacy, ranking, or priority;
- news-provider ingestion or verification implementation;
- formulas for final performance analytics;
- alpha, beta, capture, or risk-adjusted calculation methods;
- fabricated regime labels;
- a chronological news feed;
- mutation of frozen upstream artifacts;
- silently inferred values for missing state.

## 19. Invariants

1. Current state has precedence over chronological catch-up.
2. Market and portfolio are peer report domains.
3. Raw account equity is distinct from investment performance.
4. Deposits and withdrawals do not count as strategy return.
5. Current deterministic facts do not depend on `last_seen_at`.
6. Historical catch-up depends on current relevance, not chronology alone.
7. Attention normally compresses to approximately five to seven visible items.
8. P0 cannot be silently discarded because of presentation limits.
9. Discovery does not unnecessarily duplicate already-visible Attention.
10. Sentinel Evidence remains distinct from Analyst Interpretation.
11. GPT enrichment is optional.
12. Missing data never becomes neutral, normal, unchanged, or zero.
13. The report does not create trades.
14. Same deterministic inputs and configuration produce the same deterministic
    report.
15. Display-window changes do not reset account or performance history.
16. Analyst output cannot change deterministic report identity or state.

## 20. Owner-level open questions

Task 5 has no unresolved owner-level decisions. The six-item default Attention
capacity, TWR performance semantics, missing-`last_seen_at` behavior, one-time
resolved-development behavior, and always-addressable performance availability
contract are frozen for Sentinel v0.1.

## 21. Engineering and implementation-design questions

1. What normalized input contract supplies historical account equity and
   external cash flows without adding a second account representation?
2. Where is the cash-flow-adjusted performance calculation owned: Evaluation,
   an application service, or another shared read model?
3. What valuation timestamp, timezone, currency-conversion, fee, and tax policies
   govern account/performance history?
4. How are benchmark calendars, dividends, corporate actions, and missing dates
   aligned with portfolio observations?
5. What stable identifier distinguishes benchmark role from tradable symbol?
6. Which deterministic methods populate each `MarketNow` component without
   inventing a regime model?
7. Which concentration and classified-exposure measures are available from
   current normalized portfolio state?
8. What canonical mapping projects Priority component reasons into title,
   summary, and reason keys without free-form deterministic prose?
9. What exact candidate-to-Attention equivalence rule prevents Discovery
   duplication?
10. Where is HistoricalDevelopment stream state persisted, and how is it rebuilt
    in HistoricalReplay?
11. What exact predicates grade lasting/current relevance and expiry by
    development class?
12. How are report and catch-up identities separated when `last_seen_at` differs?
13. Which fields participate in `report_id`, and which presentation fields are
    deliberately excluded?
14. How are P0 overflow and hidden P1/P2 represented for clients that do not
    implement pagination?
15. What token/page semantics remain deterministic as current state changes?
16. How is deterministic one-time resolved-development presentation state stored
    without requiring manual acknowledgment or mutating report history?
17. What schema/version compatibility policy applies to stored reports and
    Analyst attachments?
18. What source/provenance schema supports Analyst news citations and revisions?
19. Which data-health gaps are material enough to raise report-level status from
    `COMPLETE` to `DEGRADED`?
20. What fixtures cover deposits, withdrawals, unavailable cash-flow history,
    benchmark gaps, last-seen differences, Discovery deduplication, and P0
    overflow?
21. What acceptance tests demonstrate 30–60-second comprehension without making
    prose or an LLM part of deterministic correctness?

## Status

DESIGN BASELINE — FROZEN FOR SENTINEL V0.1

Future substantive report-contract changes require an explicit, versioned design
revision. Engineering questions remain intentionally open for implementation and
evaluation.


## Multi-sensor design revision after 6B-2F

The [multi-sensor architecture](sentinel-multi-sensor-design.md) records the
agreed next direction, not implemented behavior or silently changed frozen
contracts. Task 6B-2G must explicitly freeze the sensor/availability and output
contracts, including any report schema revision. SPY remains one index sensor
and a portfolio benchmark; it does not alone establish market-wide conditions.
Composite references are optional evidence, not replacements for ordinal
Priority. Missing inputs remain explicit.
