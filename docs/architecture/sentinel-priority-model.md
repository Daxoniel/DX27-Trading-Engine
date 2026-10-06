# Sentinel Priority Model v0.1

## Scope

This document defines `PRIORITIZE` in Sentinel's
`SEE -> DETECT -> PRIORITIZE -> REPORT` flow. It determines which few valid
`DetectedEvent` values deserve attention now. It does not alter the frozen
Monitoring Universe or Event Taxonomy, define Blind-Spot Discovery or the final
`SentinelReport`, or authorize any action.

Priority is information-surfacing importance. It is not market direction,
expected return, trading conviction, position size, risk authorization, or
execution urgency. It must not enter `BotSignal`, Risk, Approval, Portfolio
Construction, or Execution automatically.

## 1. Priority philosophy

The governing principle is **monitor everything important; report almost
nothing**. A returning user should understand the most material changes in about
one minute without Sentinel reducing monitoring to current holdings.

The model:

1. gates invalid or uninformative inputs before evaluation;
2. ranks phenomena, not a flat list of detector emissions;
3. preserves immutable `DetectedEvent` records as factual sources;
4. aggregates related events into immutable `PriorityItem` views;
5. uses finite component grades and deterministic predicates, not an opaque
   aggregate score;
6. gives portfolio relevance meaningful but bounded influence;
7. lets broad, cross-asset, and Discovery phenomena surface without portfolio or
   watchlist membership;
8. treats repetition as continuity rather than confirmation; and
9. uses no LLM output, prose, randomness, or pseudo-probability in priority.

## 2. Priority classes

### `P0` — CRITICAL

Information whose omission would materially impair understanding of the user's
current situation. `P0` requires a severe, well-supported phenomenon involving
material portfolio structure, broad or cross-asset stress, severe market-wide
relationship failure, or concurrent critical Core changes. A large price move,
holding status, one anomalous print, or one threshold crossing is insufficient.

### `P1` — IMPORTANT

A material, current, well-supported development that is likely to change the
interpretation of the market environment, portfolio context, or an important
active theme. It can be directly portfolio-relevant, broad, cross-asset, or a
strong discovered phenomenon. It does not imply action.

### `P2` — WATCH

Valid, new or developing material information worth retaining in the short
attention set, but without sufficient significance or confirmation for `P1`.
It may be narrower, proxy-based, early, or outside known interests.

### `NOISE` — SUPPRESS

A valid event or item that fails the minimum deterministic attention predicates,
or a repeated/superseded occurrence that carries no new reportable information.
`NOISE` means suppressed now, not false or permanently unimportant.

## 3. Priority pipeline

Priority processing occurs in this order:

1. **Eligibility and quality gating**
2. **Semantic deduplication**
3. **Event clustering and aggregation**
4. **Bounded component grading**
5. **Contrary-evidence treatment**
6. **Deterministic qualification predicates and `P0` overrides**
7. **Priority-class assignment**
8. **Lexicographic deterministic ranking**
9. **Dominance suppression and top-K selection**

No stage mutates a constituent event. Same structured inputs, prior state,
effective time, model version, and configuration must produce the same result.

## 4. Eligibility and quality gates

A failed hard gate suppresses an event with a machine-readable reason rather
than assigning it a low score.

An event is ineligible when:

- a required input is `STALE`, `INSUFFICIENT_HISTORY`,
  `UNSUPPORTED_SESSION`, `SOURCE_ERROR`, or `UNAVAILABLE`;
- required structured evidence is absent or inconsistent with the event type;
- a relationship lacks valid subject alignment or overlap;
- proxy identity or its distinction from an authoritative series is unresolved;
- magnitude, baseline, subject identity, or observation time required by the
  detector contract is absent;
- its observation window is incomplete or extends beyond `observed_at`;
- it is a semantic duplicate or is superseded by a newer occurrence;
- it is unchanged `CONTINUING` with no new subject, independent confirmation,
  material strengthening, reversal, or newly relevant portfolio context;
- it is older than its configured relevance horizon; or
- it is already represented in the same cluster without a distinct measured
  fact.

Invalid data never becomes a normal conclusion. Data-health conditions remain
metadata and a broad outage does not become one priority item per affected asset.
Ineligible occurrences remain in immutable audit history.

## 5. Priority inputs

Only explicit structured information may affect priority:

- event type, economic category, direction, magnitude, baseline, semantic flags,
  lifecycle, evidence, and evidence lineage;
- normalized holding exposure, watchlist status, and explicit Contextual reason;
- individual, group, industry, sector, broad-market, or cross-asset scope;
- continuation, transition, level break, trend transition, participation shift,
  or relationship break;
- event age, lifecycle, persistence, and latest material-change time;
- independent support across subjects, evidence families, market dimensions, or
  economic categories;
- availability, completeness, alignment, authority/proxy status, and history;
- Core, Contextual, or Discovery membership and universe version.

Priority consumes the normalized portfolio snapshot and does not create another
portfolio representation. Natural-language descriptions are never inputs.

## 6. Bounded component-grade model

Sentinel v0.1 does **not** require or define a single weighted numeric priority
score. It uses:

```text
hard gates
-> semantic clustering
-> bounded component grades
-> deterministic qualification predicates
-> priority class
-> deterministic lexicographic ranking tuple
```

The finite ordinal vocabulary is `NONE < LOW < MEDIUM < HIGH`. An implementation
may encode these values as ordered integers but must not convert the component
vector into an arbitrary weighted sum.

| Component | `NONE` | `LOW` | `MEDIUM` | `HIGH` |
| --- | --- | --- | --- | --- |
| Direct relevance | no user relationship | watchlist/context | small or moderate exposure | material portfolio exposure |
| Market scope | not established | individual | group/industry/sector | broad market/cross-asset |
| Structural significance | ordinary continuation | minor state change | material transition | major break/failure |
| Magnitude/abnormality | not established | detector-material | uncommon | historically extreme |
| Independent confirmation | dominant fact only | related non-independent support | one independent lineage | two or more independent lineages spanning at least two independence axes |
| Novelty | unchanged continuation | aging/resolved update | new/strengthened | reversal or important new Discovery phenomenon |
| Time sensitivity | expired | aging but relevant | current | newly critical transition |
| Evidence quality | invalid | valid proxy/minimum complete | complete supported | authoritative and fully aligned |
| Contrary evidence | none | immaterial contrary lineage | material contrary lineage | strong independently confirmed contradiction |

Classification and ranking must remain explainable from individual components.
Event count cannot raise a component merely by repetition.

### Independent confirmation

Event count is not confirmation count. Every evidence contribution has an
`evidence_lineage_id` derived from normalized source observations, detector
family, baseline identity, evidence family, subject/group identity, and economic
category. Different event IDs do not imply different lineages.

Two facts are independent only when both conditions hold:

1. they do not derive substantially from the same observations, detector family,
   baseline, or transformed evidence lineage; and
2. at least one material independence axis differs: economic subject/group,
   evidence family, market dimension, or economic category.

Breadth versus price, credit versus equity, and volatility versus price can be
independent. Two thresholds on the same returns, or two detector IDs wrapping
the same baseline, are not. Supporting events are partitioned into deterministic
lineage-equivalence classes. `MEDIUM` requires one independent lineage beyond
the dominant fact. `HIGH` requires at least two, spanning at least two axes.
Persistence may affect lifecycle but is not independent confirmation.

### Contrary evidence

Every related event is classified relative to the cluster's explicit assertion
as `SUPPORTING`, `CONTRARY`, or `NEUTRAL`. `PriorityItem` preserves supporting
and contrary event IDs, lineage IDs, independence axes, and acceptance decisions.
Contrary evidence is never silently discarded or forced into support.

The contrary grade is applied before qualification:

- `NONE` or `LOW`: retain it; classification is unchanged;
- `MEDIUM`: reduce confirmation by one grade and block every `P0` override for
  that cycle;
- `HIGH`: set confirmation to `NONE`, cap the item at `P2`, and block every `P0`
  override for that cycle.

Ineligible contrary evidence has no effect. These roles do not create a second
event taxonomy.

### Deterministic qualification matrix

After contrary-evidence effects, classification proceeds exactly once in order:

1. Assign `P0` only when a Section 7 override predicate is true.
2. Otherwise assign `P1` when **all** are true:
   - evidence quality is at least `MEDIUM`;
   - magnitude is at least `MEDIUM`;
   - time sensitivity is at least `MEDIUM`;
   - independent confirmation is at least `MEDIUM`; and
   - structural significance or market scope is `HIGH`, **or** direct relevance
     is `HIGH` with structural significance at least `MEDIUM`.
3. Otherwise assign `P2` when **all** are true:
   - evidence quality is at least `LOW`;
   - magnitude is at least `LOW`;
   - time sensitivity is at least `LOW`;
   - lifecycle is information-bearing (`NEW`, `STRENGTHENED`, `WEAKENED`,
     `RESOLVED`, or `REVERSED`), not unchanged `CONTINUING`; and
   - direct relevance, market scope, structural significance, independent
     confirmation, or novelty is at least `MEDIUM`.
4. Otherwise assign `NOISE`.

Hard-gated inputs are `NOISE` for visible selection with their gate reason
preserved. Top-K can suppress a valid `P1` or `P2`, but never changes its class.
Thus identical component vectors cannot be classified differently.

### Reproducibility identity

Each item carries:

- `priority_model_version`, identifying model semantics and processing; and
- `priority_config_id`, deterministically identifying the complete immutable
  effective configuration.

Changing qualification predicates, grade definitions, caps, override rules, or
ranking semantics changes the relevant model version and configuration identity.
Changing cooldowns, horizons, clustering rules, or role mappings also changes
`priority_config_id`.

Same events, portfolio/universe context, prior state, effective time, model
version, and configuration must produce identical items, classes, and ranking.

## 7. `P0` override rules

`P0` is available only to a cluster, never an isolated uncontextualized number.
At least one versioned predicate must be satisfied:

1. **Material exposure structural break:** material portfolio exposure, a major
   structural transition/reversal, high abnormality, and independent
   confirmation.
2. **Confirmed broad stress:** broad-market deterioration plus independent
   confirmation from at least two distinct roles such as credit, volatility,
   rates, or participation.
3. **Severe relationship failure:** a high-scope relationship break of extreme
   normalized magnitude, adequate aligned evidence, and an independent fact.
4. **Critical Core concurrence:** simultaneous material transitions across the
   configured minimum of distinct critical Core roles, coherently clustered.

All predicates require current data, `HIGH` evidence quality, no `MEDIUM` or
`HIGH` contrary evidence, and the evidence required by that predicate. No rule
such as “a holding fell 5%” is sufficient.

Proxy evidence may contribute to priority and independent confirmation. However,
proxy-only evidence for an unobserved authoritative economic series cannot by
itself trigger a macro/cross-asset `P0` override claiming the underlying state
was observed. Proxy identity remains explicit, and any qualifying `P0` requires
the authoritative observation or independent non-proxy evidence sufficient for
the predicate without relabeling the proxy.

Overrides affect reporting only and authorize no action.

## 8. Event clustering and `PriorityItem`

Priority produces a separate immutable view:

```text
PriorityItem
├── priority_schema_version
├── priority_model_version
├── priority_config_id
├── item_id
├── evaluated_at
├── constituent_event_ids[]
├── supporting_event_ids[]
├── contrary_event_ids[]
├── evidence_lineages[]
├── primary_subjects[]
├── economic_category
├── scope
├── dominant_event_type
├── supporting_event_types[]
├── relevance_context
├── lifecycle_summary
├── component_grades
├── override_reason?
├── priority_class
├── suppression_reasons[]
├── explanation_factors[]
└── ranking_tuple
```

IDs and lineages are canonically ordered. Events cluster only under configured
compatibility for category/subject ancestry, observation windows, direction,
relationship/benchmark, and explicit role mapping. Simultaneity, a shared ticker,
or a convenient narrative is insufficient. Contrary facts remain contrary or
form a separate cluster.

The dominant event is chosen by structural specificity, scope, evidence quality,
and the frozen taxonomy precedence. Related semiconductor leadership facts may
be one item; an unrelated company-specific gap remains separate.

## 9. Deduplication, recurrence, and lifecycle

Task 2's `deduplication_key` identifies a semantic stream. Priority state tracks
the latest eligible occurrence and latest surfaced material state.

- `NEW`: full evaluation with bounded novelty.
- `CONTINUING`: suppressed unless there is material new information.
- `STRENGTHENED`: reevaluate changed components and confirmation.
- `WEAKENED`: reduce importance; surface only material de-escalation.
- `RESOLVED`: eligible to close a surfaced phenomenon; ordinarily not `P0`.
- `REVERSED`: full reevaluation as new structural information.

A continuing condition recurs visibly only if it materially strengthens,
reverses, expands to new subjects, gains independent confirmation, or becomes
newly portfolio-relevant. Repetition and elapsed time do not increase priority.
Cooldowns and horizons are cadence/type-specific configuration.

Replay begins from explicit prior priority state or a declared cold start. Age
uses structured event time and configured effective time, never incidental wall
clock execution time.

## 10. Portfolio relevance

Priority consumes normalized portfolio context without owning it:

- normalized exposure matters more than a bare holding flag;
- material exposure raises relevance for an otherwise equivalent item;
- an ordinary event in a small holding remains `NOISE` or `P2`;
- watchlist and Contextual activation give bounded relevance, not visibility;
- relevance cannot repair invalid data or weak semantics;
- broad/cross-asset scope can outrank a holding-specific item; and
- no portfolio relationship is required for `P1` or `P2`.

Priority never modifies positions or infers desired exposure.

## 11. Discovery and anti-anchoring

Discovery provenance is bounded novelty, neither a penalty nor automatic
importance. An unowned discovery reaches `P1` under the same qualification
matrix, `P2` when meaningful but less significant/confirmed, and `NOISE` when
isolated or weak.

No non-portfolio slot is reserved aesthetically. Instead, market scope and
structural significance precede direct relevance in ranking, and classification
does not require ownership. Task 4 determines how blind spots are discovered;
Task 3 only prioritizes valid supplied events.

## 12. Top-K selection and `P0` overflow

The default visible maximum is five items per scan/report cycle:

1. retain all distinct `P0` candidates for overflow handling;
2. sort by the canonical ranking tuple;
3. suppress items substantially subsumed by a selected cluster;
4. select remaining `P1`, then `P2`, until five slots are filled; and
5. retain machine-readable suppression reasons.

Dominance suppression removes semantic redundancy, not diversity for appearance.
One dominant phenomenon should carry its support inside one item; genuinely
distinct phenomena in the same category may occupy multiple slots.

If more than five distinct `P0` phenomena remain, related raw observations are
first aggregated at the broadest defensible phenomenon. The first five are
visible; every remaining item stays `P0` as critical overflow. Nothing is
downgraded or silently dropped. Overflow count and completeness are inputs to
the later reporting contract.

## 13. Deterministic ranking

Ranking cannot change an assigned class. Items are ordered lexicographically,
descending unless noted, by:

1. priority class (`P0`, `P1`, `P2`, `NOISE`);
2. structural significance;
3. market scope;
4. independent confirmation;
5. direct portfolio materiality;
6. magnitude/abnormality;
7. evidence quality;
8. novelty/lifecycle significance;
9. latest material-change `observed_at`;
10. canonical `item_id` ascending.

Structural significance and scope precede portfolio materiality to prevent
ownership anchoring while still letting exposure break otherwise equal ties.
Contrary evidence has already deterministically adjusted confirmation and caps.
No weighted aggregate, prose, iteration order, locale, or random value may enter
the tuple.

## 14. Explainability

Every result is reconstructable from constituent IDs, evidence lineages,
component grades, gates, contrary adjustments, override predicate,
qualification predicate, lifecycle, ranking tuple, suppression decisions, model
version, and configuration identity.

Structured explanation factors may include `BROAD_SECTOR_SCOPE`,
`ABNORMAL_RELATIVE_STRENGTH`, `INDEPENDENT_ACTIVITY_CONFIRMATION`,
`DISCOVERED_OUTSIDE_KNOWN_INTEREST`, and `NO_DIRECT_PORTFOLIO_EXPOSURE`.
Prose may render these facts later but cannot determine priority.

## 15. Worked examples

These examples do not freeze market-specific numeric thresholds.

### 1. Large portfolio holding breaks major structure

A material holding crosses below a major level, changes trend, shows abnormal
activity, and gains an independent confirmation lineage. It forms one item and
satisfies the material-exposure override: **`P0`**. Without confirmation it does
not qualify for `P0` and is normally **`P2`** or **`P1`** only if the exact `P1`
matrix is satisfied by other independent evidence.

### 2. Small holding has an ordinary daily move

A small holding produces ordinary continuation without abnormality or transition.
Relevance alone cannot pass the predicates: **`NOISE`**.

### 3. Unowned sector develops strong leadership

Sector relative strength, independent abnormal activity, and participation
broadening produce high scope, magnitude, and confirmation: **`P1`**, despite no
portfolio exposure.

### 4. Broad index rises while breadth deteriorates

An index advance, narrowing authoritative breadth, and their divergence form a
broad structural item with independent price/breadth evidence: **`P1`**. Missing
breadth data fails the gate instead of implying normal participation.

### 5. Credit weakens while equities remain strong

An authoritative credit-spread deterioration plus equity/credit divergence is
cross-asset and independently confirmed: **`P1`**. Severe credit, volatility,
and equity deterioration could meet a `P0` override; a credit ETF alone cannot
claim that authoritative spread state.

### 6. Repeated continuing event with no new information

A breakout remains valid for six bars without material change. Repetition is not
confirmation and unchanged `CONTINUING` fails eligibility: **`NOISE`** now.

### 7. Same condition materially strengthens

The breakout becomes extreme and gains independent activity confirmation.
`STRENGTHENED` triggers reevaluation and may move **`P2` to `P1`** if the exact
matrix is satisfied.

### 8. Semiconductor events collapse into one item

Relative strength, activity, participation, and synchronization describe one
leadership phenomenon. They become one **`P1` `PriorityItem`**, with independent
and non-independent lineages distinguished, rather than four visible entries.

### 9. Proxy observation versus authoritative series

A credit ETF proxy with explicit identity can provide valid `LOW` quality
context and become **`P2`**. An authoritative spread with otherwise equivalent
evidence can qualify for **`P1`**. Proxy-only evidence cannot trigger the
macro/cross-asset `P0` override for the unobserved spread.

### 10. More than five raw critical observations

Twelve critical observations describe three coherent phenomena and aggregate
into three visible **`P0`** items. If seven distinct critical phenomena remain,
five are visible and two remain `P0` overflow with a recorded count.

### 11. Large noisy single-stock move in Discovery

One extreme move lacks independent activity, group, or structural support. It
fails the `P1` matrix and normally becomes **`NOISE`**, or **`P2`** only if an
information-bearing structural fact passes every P2 predicate.

### 12. Broad event with no portfolio position

A broad structural break with independent participation and cross-asset support
qualifies **`P1`** or a configured **`P0`** override. No holding is required.

## 16. Explicit exclusions

This model does not define Monitoring Universe membership, event detection,
Blind-Spot scoring, `SentinelReport`, prose generation, probabilistic confidence,
return forecasts, trades, portfolio targets, risk/approval decisions, bot
control, execution, provider access, or infrastructure telemetry.

## 17. Invariants

1. Same structured inputs, prior state, effective time, model version, and
   configuration produce the same result.
2. Priority never mutates `DetectedEvent`.
3. Priority never creates or authorizes trades.
4. Priority never depends on LLM prose.
5. Portfolio relevance matters but is not mandatory.
6. Discovery can surface outside known interests.
7. Invalid data cannot gain priority.
8. Repetition alone cannot increase priority.
9. Independent confirmation may increase priority.
10. Contrary evidence remains explicit.
11. Priority is explainable from machine-readable components.

## 18. Open questions before design freeze

1. What market-specific thresholds map normalized observations to finite grades?
2. What normalized exposure measure maps portfolio state to relevance grades?
3. What canonical subject/group ancestry supports deterministic clustering?
4. What window separation permits clustering at daily and 15-minute cadences?
5. What exact source-observation identity defines evidence-lineage equivalence?
6. Which type-specific horizons, cooldowns, and material-change rules apply?
7. How is prior priority state persisted and initialized for replay?
8. What canonical serialization/hash defines item and configuration IDs?
9. Which non-proxy inputs may independently satisfy each macro `P0` predicate?
10. Which Core roles participate in critical-Core concurrence?
11. Should resolved items consume a visible slot or update an existing item?
12. How long is critical overflow retained for later reporting?
13. What audit form records gate and top-K suppression without surfacing noise?
14. What compatibility policy applies across model/configuration changes?
15. Which fixtures validate every class predicate, evidence-lineage decision,
    contrary-evidence cap, override, recurrence, tie-break, and overflow rule?
16. What acceptance measures prove concise reporting without systematically
    hiding important Discovery or broad-market developments?

These questions must be resolved before the design is marked frozen. They do not
authorize implementation or changes to the frozen Task 1 and Task 2 documents.
