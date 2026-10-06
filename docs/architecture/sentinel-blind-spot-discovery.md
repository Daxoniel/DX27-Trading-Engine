# Sentinel Blind-Spot Discovery v0.1

## Scope

This document defines the deterministic Blind-Spot Discovery design for the
Sentinel `SEE -> DETECT -> PRIORITIZE -> REPORT` flow. Discovery asks what
important market structure is developing outside current holdings, watchlists,
active Contextual observations, and active hypotheses.

Discovery is observation-scope intelligence. It does not trade, recommend,
produce `BotSignal` objects, assign `P0`/`P1`/`P2`, or define the final report.
The frozen Monitoring Universe, Event Taxonomy, and Priority Model remain the
authoritative upstream and downstream contracts.

## 1. Discovery philosophy

Blind-Spot Discovery follows these principles:

1. **Search broadly and preserve reasonable recall.** Approximately 500
   eligible, liquid US-listed assets may be screened daily. The deterministic
   layer may retain more plausible candidates than are ultimately shown to the
   user; downstream analysis and priority remain responsible for attention
   compression.
2. **Discover structure, not movers.** Leadership, participation, coherence,
   persistence, and relationships matter more than an isolated return or
   volume spike.
3. **Use evidence-appropriate granularity.** Economically related multi-member
   behavior is usually stronger than an unexplained single-name anomaly, but
   high-dispersion themes and material idiosyncratic exceptions must remain
   observable.
4. **Novelty means changed market information.** It does not mean that a ticker
   has never appeared before.
5. **Known interests do not veto evidence.** Holdings and hypotheses expand
   context but cannot suppress contradictory discoveries.
6. **Use explicit predicates, not a black-box score.** Quality gates,
   deterministic discovery predicates, and finite candidate states replace a
   weighted `DiscoveryScore`.
7. **Preserve established boundaries.** Discovery uses the frozen event types
   and passes valid events to the frozen Priority Model.
8. **Completed data only.** Daily v0.1 discovery uses completed observations and
   remains compatible with immutable historical prefixes.

The governing product rule is:

> Find previously under-observed market structure with reasonable recall,
> without becoming a largest-mover scanner or a permanently expanding
> watchlist.

## 2. Architectural placement

The normative flow is:

```text
versioned DISCOVERY universe
        -> quality and eligibility gates
        -> deterministic broad screening
        -> canonical economic grouping
        -> persistence, coherence, and novelty predicates
        -> DiscoveryCandidate state transition
        -> frozen DETECT semantics / DetectedEvents
        -> frozen Priority Model
        -> optional future Analyst enrichment
```

Screening measurements may identify facts that detectors express using the
frozen Event Taxonomy. A `DiscoveryCandidate` references those facts and says
that a previously under-observed area deserves closer observation. It is not a
new market-event taxonomy or a priority artifact.

Discovery may request deterministic `CONTEXTUAL` activation after promotion.
That changes observation scope only. It cannot change portfolio state, trigger
execution, or assign reporting priority.

### 2.1 Future Analyst enrichment boundary

A future LLM/GPT Analyst may interpret already-formed candidates, research
relevant catalysts, connect companies, groups, macro variables, and events,
challenge or support hypotheses, and propose whether closer observation is
warranted. This enrichment is downstream of deterministic facts and candidacy.

The Analyst:

- cannot create raw market facts or modify `DetectedEvent` objects;
- cannot assign deterministic `P0`, `P1`, or `P2`;
- must attribute every claim to structured evidence and source provenance;
- may offer interpretations and alternatives, but cannot silently alter
  deterministic candidate or promotion state;
- is optional: the complete deterministic workflow must operate without it.

Future user-facing output may display Analyst enrichment without requiring
user approval merely to show it, but it must present two conceptually separate
layers:

- **Sentinel Evidence:** deterministic candidates, events, measurements, state,
  and provenance;
- **Analyst Interpretation:** possible catalysts, company/group relationships,
  interpretations, alternative explanations, hypothesis contradictions,
  falsification conditions, and source-backed research.

Analyst Interpretation must remain provenance-aware and visibly distinguishable
from Sentinel Evidence. It cannot mutate events, independently assign priority,
activate Contextual monitoring, or authorize trading or execution.

This boundary is reserved for future work and is not a v0.1 implementation
dependency.

## 3. Known-interest semantics

### 3.1 Known-interest snapshot

Known interest is evaluated from a versioned, point-in-time snapshot at the
scan's `observed_at`. It contains:

- current nonzero portfolio holdings from normalized portfolio state;
- the explicit watchlist version active at that time;
- active Contextual members and their activation reasons;
- active, versioned research hypotheses and their declared subject/category
  coverage;
- previously surfaced, unexpired Discovery candidates.

The snapshot must not infer interest from prose, browsing behavior, or an LLM.
Membership is determined by stable subject identifiers, canonical group
identifiers, and explicit relationship metadata.

### 3.2 Overlap states

For each candidate, `known_interest_overlap` records a finite state:

- `NONE`: neither its canonical group nor its material members are known;
- `PARTIAL`: some members or an adjacent economic role are known;
- `GROUP_KNOWN`: the canonical group is already an active interest;
- `DIRECT`: the primary subject is held, watchlisted, Contextual, or covered by
  an active hypothesis.

Overlap is descriptive. `NONE` does not automatically promote a candidate, and
`DIRECT` does not disqualify one. Blind-spot status requires `NONE` or `PARTIAL`
at initial formation; material character changes in a known theme may still be
tracked as candidate lifecycle updates rather than falsely relabeled unknown.

### 3.3 Interest lifecycle

A useful observation-scope lifecycle is:

```text
UNKNOWN -> DISCOVERED -> CONTEXTUAL -> EXPIRED -> DISCOVERY-ELIGIBLE
```

- `UNKNOWN` means eligible but absent from the known-interest snapshot.
- `DISCOVERED` means an active candidate exists.
- `CONTEXTUAL` means deterministic promotion activated closer observation.
- `EXPIRED` means the candidate or activation ended.
- Return to discovery eligibility occurs after the configured cooldown or
  reevaluation rule; it is not a permanent exclusion.

These are discovery-scope states, not Task 2 event lifecycle values. Event
lifecycle remains attached to immutable event streams.

## 4. `DiscoveryCandidate` concept

### 4.1 Purpose

`DiscoveryCandidate` is an immutable snapshot of a stateful discovery stream:

> This previously under-observed subject or economic group has enough valid,
> structured evidence to deserve closer observation.

It is not a `DetectedEvent`, `PriorityItem`, watchlist entry, recommendation,
forecast, or trade signal.

### 4.2 Conceptual schema

```text
DiscoveryCandidate
├── schema_version
├── candidate_id
├── candidate_stream_key
├── discovery_model_version
├── discovery_config_id
├── observed_at
├── evaluation_window
├── source_universe_version
├── known_interest_snapshot_id
├── classification_metadata_version
├── primary_subjects[]
├── canonical_group?
│   ├── group_id
│   ├── group_kind
│   ├── economic_category
│   └── membership_version
├── constituent_event_ids[]
├── evidence_lineages[]
├── discovery_families[]
├── evidence_vector
│   ├── relative_leadership
│   ├── activity
│   ├── participation
│   ├── coherence
│   ├── structural_change
│   └── contradiction
├── novelty_state
├── persistence_state
├── coherence_state
├── observation_granularity
├── known_interest_overlap
├── quality_state
├── candidate_state
├── promotion_state
├── promotion_reasons[]
├── promotion_path?
├── first_observed_at
├── last_material_change_at
├── reevaluate_at
├── contextual_ttl_expires_at?
├── expires_at?
└── provenance
```

### 4.3 Identity

- `candidate_id` identifies this immutable candidate snapshot and should be
  derived from canonical content.
- `candidate_stream_key` identifies the continuing phenomenon across scans. It
  includes canonical subject/group identity, discovery family set, relevant
  comparison roles, and configuration identity, but excludes volatile evidence
  values.
- Subject IDs and event IDs are canonically sorted before hashing.
- A materially different group, comparison benchmark, or discovery predicate
  creates a distinct stream.

### 4.4 Candidate states

`candidate_state` uses:

- `NEW`
- `PERSISTING`
- `STRENGTHENING`
- `WEAKENING`
- `RESOLVED`

These describe the candidate stream, not the lifecycle of any constituent
event. Each snapshot preserves the event IDs and measurements that justify its
state transition.

## 5. Quality gates

Quality gates run before candidate formation. Failure suppresses candidate
creation; it is recorded as coverage/data metadata rather than a market event.

### 5.1 Subject eligibility gates

Every material subject must:

- belong to the point-in-time Discovery Universe version;
- pass the frozen liquidity and price/history requirements;
- have a stable instrument identifier;
- use supported session and adjustment semantics;
- provide valid completed OHLCV observations;
- meet the configured minimum history for each required metric;
- not be a penny stock, microcap, or economically redundant instrument under
  the versioned universe rules;
- not be a leveraged or inverse product unless the configuration explicitly
  assigns it an information role;
- not be halted, stale, unavailable, or affected by an unresolved corporate-
  action discontinuity.

### 5.2 Evidence gates

Candidate evidence must:

- have `AVAILABLE` required inputs;
- use aligned observation windows and comparison sessions;
- name its benchmark and baseline;
- expose metric units and sufficient sample counts;
- preserve detector and evidence lineage;
- avoid unresolved proxy ambiguity;
- meet at least one configured material-change predicate;
- contain no future observations or future membership metadata.

`STALE`, `INSUFFICIENT_HISTORY`, `UNSUPPORTED_SESSION`, `SOURCE_ERROR`, or
`UNAVAILABLE` required evidence cannot create or strengthen a candidate.

### 5.3 Group gates

Group evidence additionally requires:

- an explicit group definition and membership version;
- a configured minimum eligible-member count or coverage fraction;
- disclosure of eligible, observed, missing, and excluded member counts;
- no use of current membership as a substitute for unknown historical
  membership;
- sufficient independent member coverage to prevent one constituent from
  masquerading as group behavior.

When these requirements are not met, participation and coherence detection is
operationally gated. The system may retain eligible single-subject facts, but
must not claim group discovery.

### 5.4 Pump-like isolation

An isolated extreme move with extreme activity is suppressed from ordinary
candidate formation when it lacks persistence, peer confirmation, structural
importance, or a documented relationship to a monitored economic role. The
move remains a valid primitive market observation if its detector requirements
are met; suppression applies only to discovery candidacy.

## 6. Discovery families

Discovery families are predicates over frozen primitive events and structured
measurements. They are not event types.

### 6.1 Unexpected relative leadership

Purpose: find subjects or groups becoming stronger relative to the broad market
or a parent group.

Minimum concept:

- a valid `RELATIVE_STRENGTH_CHANGE` against an explicit benchmark;
- a material improvement in relative state or cross-sectional rank;
- persistence or independent group/structural confirmation;
- initial known-interest overlap of `NONE` or `PARTIAL` for a new blind spot.

Useful comparisons are asset versus `SPY`, industry versus parent sector, and
sector versus broad market. Absolute gains are not required; leadership can
emerge through relative resilience in a falling market.

### 6.2 Abnormal activity

Purpose: identify unusual volume or traded-value participation.

Minimum concept:

- `ACTIVITY_ANOMALY` with an explicit seasonal/historical baseline;
- valid liquidity and history;
- group recurrence, peer confirmation, persistence, or another structural fact.

Activity alone is supporting evidence for a group and normally insufficient for
a single-name candidate.

### 6.3 Group coherence and synchronization

Purpose: identify economically related members beginning to behave together.

Minimum concept:

- a versioned economic group with adequate member coverage;
- `RELATIONSHIP_CHANGE` using group-coherence semantics and/or a valid
  `PARTICIPATION_CHANGE`;
- multiple members contributing rather than a single dominant constituent;
- improvement relative to the group's own prior coherence baseline.

### 6.4 Sector or industry rotation

Rotation is a composition, normally requiring:

- `RELATIVE_STRENGTH_CHANGE`; and
- `PARTICIPATION_CHANGE` or group `RELATIONSHIP_CHANGE`; and
- persistence across completed sessions;
- optional `ACTIVITY_ANOMALY` or structural price confirmation.

No `SECTOR_ROTATION` event is introduced.

### 6.5 Broadening or narrowing participation

Purpose: detect changes in how many members support a group move.

The predicate uses `PARTICIPATION_CHANGE` with versioned membership, observed
coverage, and a declared participation metric. Operational detection remains
gated where reliable point-in-time group membership is unavailable.

### 6.6 Structural price change

Purpose: find group-level structural transitions rather than isolated breakouts.

Minimum concept:

- `PRICE_LEVEL_INTERACTION` or `TREND_CHANGE` across multiple members;
- valid, independently derived level/trend evidence;
- adequate participation or coherence;
- persistence or confirmation beyond one isolated observation.

### 6.7 Cross-asset or macro contradiction

Purpose: expose facts inconsistent with a current market narrative or with
normally related market dimensions.

Minimum concept:

- valid `RELATIONSHIP_CHANGE`, `SERIES_STATE_CHANGE`, or other frozen primitive
  events;
- explicit expected relationship and aligned windows;
- economically meaningful subjects or series;
- authoritative data or explicit proxy identity.

Examples include equities versus credit, growth versus rates, defensive-sector
leadership versus broad risk appetite, and commodities versus a stated macro
hypothesis. Contradictions are observations, not trading interpretations.

### 6.8 Theme emergence outside known interest

Purpose: form a candidate from a coherent cluster not already held,
watchlisted, Contextual, or covered by an active hypothesis.

The cluster must satisfy quality gates and combine persistent relative
leadership with at least one of:

- multi-member coherence;
- broadening participation;
- repeated abnormal activity across members;
- synchronized structural transitions;
- a documented cross-market economic relationship.

## 7. Novelty semantics

### 7.1 Novelty states

Novelty is a finite, deterministic state:

- `NEW_PHENOMENON`: no active or cooldown candidate represents the same
  canonical phenomenon;
- `NEW_LEADERSHIP_STATE`: the relative rank/state crossed a configured material
  boundary;
- `NEW_COHERENCE`: a formerly dispersed group now meets coherence predicates;
- `CHARACTER_CHANGED`: a known theme acquired a materially different evidence
  family, direction, group breadth, or relationship;
- `UNCHANGED`: the phenomenon remains within its last material state;
- `RETURNED`: a resolved/expired phenomenon requalifies after its configured
  return rule.

### 7.2 Normative novelty rule

A candidate is novel only when the current completed-data snapshot produces a
material state transition relative to prior discovery state under the same
configuration. A new event ID, a new ticker, or another day of the same ranking
is insufficient.

Repeated unchanged leadership receives `UNCHANGED`, does not create a new
candidate stream, and cannot strengthen solely through age. A known theme may
become novel again through material broadening, acceleration, reversal, new
independent evidence, or a changed economic relationship.

## 8. Persistence semantics

### 8.1 Persistence evidence

Persistence is evaluated from completed sessions and may be established by:

- the same qualifying condition recurring across configured reevaluations;
- sustained relative-state improvement rather than a one-session spike;
- repeated confirmation by multiple group members;
- survival of the predicate after a configured cooling observation;
- continuing structure while evidence breadth or coherence remains valid.

Exact windows are configuration decisions, but every predicate names its
window, required observations, permitted gaps, and minimum coverage.

### 8.2 Persistence states

- `UNCONFIRMED`: first qualifying observation without a structurally sufficient
  same-cycle group confirmation;
- `CONFIRMED`: the persistence predicate has been met;
- `STRENGTHENING`: evidence crosses a configured higher material state through
  broader participation, stronger coherence, or greater persistent change;
- `WEAKENING`: evidence remains valid but retreats materially;
- `FAILED`: confirmation did not arrive within the reevaluation horizon;
- `RESOLVED`: the underlying predicate no longer holds.

A coherent multi-member condition may qualify in one daily scan when its
independent same-cycle evidence is structurally sufficient; this is not treated
as temporal persistence. The candidate must record whether support is temporal,
cross-sectional, or both.

### 8.3 No repetition bonus

Unchanged recurrence does not accumulate an ever-higher score. It maintains
state until reevaluation or expiry. Only a material state transition can mark a
candidate `STRENGTHENING` or create new information for downstream priority.

## 9. Adaptive observation granularity

Discovery selects a deterministic observation granularity for each canonical
economic area. Granularity is configuration-driven and must be recorded on the
candidate. It is not permanently hard-coded by sector name.

### 9.1 Granularity modes

- `GROUP_FIRST`: represent the common phenomenon primarily through its canonical
  group. This is appropriate when constituent behavior is strongly dominated by
  a common factor and idiosyncratic dispersion is low. Member evidence remains
  retained, but routine constituent observations do not become separate
  candidates.
- `GROUP_AND_MEMBERS`: represent both the group phenomenon and materially
  distinct member trajectories. This is appropriate for high-beta or
  high-dispersion themes, including semiconductors and AI infrastructure, where
  individual companies may diverge economically and structurally.
- `MEMBER_EXCEPTION`: a normally group-driven area may surface one member when
  deterministic evidence establishes material idiosyncratic behavior.

`MEMBER_EXCEPTION` requires a valid group comparison plus evidence such as
residual performance versus the group, abnormal activity, a structural
transition, peer divergence, or a verified company-specific catalyst. A raw
return or volume rank alone is insufficient.

### 9.2 Selection semantics

The effective v0.1 granularity comes only from versioned configuration.
Measured cross-sectional dispersion, residual performance, correlation,
concentration, and stability may be computed and may recommend a possible mode
change, but they must not automatically switch a group's observation mode in
the initial v0.1 configuration.

Automatic transitions are deferred until historical replay and evaluation
demonstrate stable deterministic rules. Any future automatic transition
semantics must be versioned, and a transition must not retroactively rewrite
earlier candidates.

The same group may use different modes in different regimes only when the
configured transition predicate is satisfied. An LLM, unverified news, or
subjective narrative cannot select granularity.

### 9.3 Canonical groups

Permitted group sources are:

- versioned sector membership;
- versioned industry membership;
- curated, versioned economic-role groups;
- curated AI/data-center or supply-chain relationships already declared in
  metadata;
- future security-master classifications.

Groups cannot be invented dynamically from narrative labels or LLM output.
Purely statistical clusters may be explored later, but v0.1 requires a stable,
explainable economic or classification identity.

### 9.4 Canonical representation

Correlated members of the same phenomenon are represented by one canonical
group candidate when:

- they share a versioned group or economic relationship;
- their observation windows overlap;
- their directions and discovery family are compatible;
- the group satisfies coverage and coherence gates.

The group candidate retains all qualifying subject and event IDs. Under
`GROUP_FIRST`, it does not emit one candidate per constituent. Under
`GROUP_AND_MEMBERS` or a valid `MEMBER_EXCEPTION`, separate member candidates
are permitted only for materially distinct trajectories supported by distinct
evidence. Separate candidates also remain appropriate when the same company
participates in materially different economic phenomena.

### 9.5 Currently available versus future metadata

**Currently available in principle:** completed normalized OHLCV, eligible
US-listed subjects, broad ETF comparisons, current portfolio overlap, and
manually versioned groups whose membership is committed as design/configuration
data.

**Requires future metadata or data sources:** authoritative point-in-time index,
sector, and industry membership; comprehensive security-master classification;
corporate-action history; dynamic supply-chain metadata; exchange breadth;
authoritative rates and credit series; and reliable local-market group data.

Absent metadata gates the associated group claim. It must not be guessed from
company names, current constituents, or provider categories inside discovery
logic.

## 10. Single-name noise control

### 10.1 Default rule

A liquid Discovery stock rising 15% on four-times-normal volume does **not**
automatically form a `DiscoveryCandidate`. It may produce `PRICE_GAP`,
`PRICE_LEVEL_INTERACTION`, `TREND_CHANGE`, `ACTIVITY_ANOMALY`, or
`VOLATILITY_CHANGE` events, but large movement plus volume alone is a mover
scan, not blind-spot structure.

### 10.2 Single-name exception predicate

An isolated subject may form a candidate only when all quality gates pass and
at least one structural-importance condition plus one independent confirmation
condition holds.

Structural-importance conditions:

- the subject has a versioned, material role in a major economic group or Core
  relationship;
- its liquidity/market significance meets a configured high-materiality class;
- it represents a unique upstream/downstream observation not available through
  a broader group proxy;
- it undergoes a persistent structural transition rather than a one-day move.

Independent confirmation conditions:

- related peers or the parent group confirm;
- relative strength persists across completed sessions;
- a distinct relationship event confirms the economic role;
- structural and activity evidence arise from materially distinct evidence
  lineages;
- the condition survives reevaluation after the initial anomaly.

Different event IDs derived from the same price/volume bar are not independent
confirmation. When the exception does not hold, the event remains available to
ordinary DETECT processing but is not promoted as a blind-spot candidate.

## 11. Candidate promotion

### 11.1 Meaning

Promotion means:

> Activate closer, time-bounded Contextual observation of this subject or group.

It never means buy, sell, recommend, authorize risk, or assign priority.

### 11.2 Common promotion gates

A candidate is eligible for `CONTEXTUAL` activation only when all required
quality gates remain satisfied, its canonical identity and membership are
stable, and one of the two deterministic promotion paths qualifies. Neither
path assigns attention priority.

### 11.3 Normal path

The normal path requires:

```text
persistent discovery condition
    + independent confirmation from at least one additional evidence dimension
```

For example, persistent relative leadership plus broadening participation may
qualify. Other valid independent dimensions include group coherence, structural
transition, a distinct relationship, or repeated abnormal activity. Volume is
not mandatory. Multiple metrics derived from substantially the same underlying
observations or lineage do not constitute independent confirmation.

### 11.4 Fast path

The fast path requires:

```text
verified material event or catalyst
    + strong market confirmation
```

Examples include a material policy, order, earnings, or regulatory event
confirmed by price structure, activity, peers, or an economically related
group. The catalyst must have structured identity, time, affected subjects,
source provenance, and a verifiable evidence basis. Unverified news, rumor, or
LLM interpretation cannot qualify the fast path. Where verified structured
event data is unavailable, the fast path is operationally gated; the normal
path remains fully functional without news.

Exact windows and market-specific thresholds remain configuration decisions,
but the two semantic paths are normative.

The capability state must distinguish:

- `FAST_PATH_SUPPORTED`: the Discovery model and schema implement the frozen
  fast-path semantics;
- `FAST_PATH_ENABLED`: the effective versioned configuration has an approved
  structured catalyst source and permits fast-path evaluation.

The fast path is part of the v0.1 design and therefore
`FAST_PATH_SUPPORTED=true`. The initial v0.1 configuration must set
`FAST_PATH_ENABLED=false` whenever no approved structured catalyst source is
available. GPT judgment, ordinary web/news prose, rumor, or unsupported
inference can never substitute for that source or turn the path on.

### 11.5 Promotion reasons

Allowed promotion reasons are:

- `PERSISTENT_LEADERSHIP`;
- `MULTI_MEMBER_COHERENCE`;
- `BROADENING_PARTICIPATION`;
- `REPEATED_ABNORMAL_ACTIVITY` with independent structural support;
- `STRUCTURAL_TRANSITION` across a meaningful group;
- `CROSS_MARKET_RELEVANCE`;
- `NEW_ECONOMIC_CATEGORY` absent from known interests;
- `MATERIAL_CONTRADICTION` to an active hypothesis.

Promotion produces an explicit activation reason, activation timestamp,
promotion path, reevaluation schedule, expiry rule, and subject/group scope. It
is idempotent: repeated identical qualification cannot create duplicate
activations.

### 11.6 Contextual activation TTL

The frozen v0.1 default is:

```text
default_contextual_ttl = 30 calendar days
```

Expiry is calculated from the latest material confirmation, not from every
unchanged observation. A new material confirmation that satisfies the active
promotion path resets the horizon to 30 calendar days and is recorded in state.
Explicit invalidation may demote the candidate earlier.

The architecture may support versioned category-specific TTL overrides, but the
initial v0.1 configuration uses the same 30-day default for every category.
Empirical evaluation must justify any later exception, and changing category
TTL policy must change `discovery_config_id`.

The TTL is an observation-scope lifetime, not a candidate-retention limit.
Historical candidate, evidence, promotion, and expiry state remains auditable
after observation scope expires.

## 12. Candidate expiry and demotion

### 12.1 Expiry conditions

A candidate becomes `WEAKENING`, `RESOLVED`, or expired when a versioned rule
detects one or more of:

- relative leadership materially disappears or reverses;
- group coherence or participation falls below its valid state;
- abnormal activity normalizes without other support;
- temporal confirmation fails to arrive within the reevaluation horizon;
- no material new information occurs through the configured maximum age;
- the group becomes economically redundant with another canonical candidate;
- required data quality or membership coverage deteriorates;
- classification metadata invalidates the former grouping;
- a verified catalyst is invalidated.

### 12.2 Demotion semantics

Expiry ends the discovery candidate and any discovery-originated Contextual
activation according to the recorded rule. It does not remove a holding,
watchlist entry, or Contextual activation owned by another reason.

Resolved state and its reason remain auditable. After a configured cooldown,
the subject/group returns to ordinary Discovery eligibility. Requalification
requires current predicates; old evidence cannot keep the universe expanded.

Demotion may occur before the 30-day TTL when leadership reverses, coherence
collapses, a catalyst is invalidated, required data quality fails, or supporting
market structure disappears. If none occurs, the activation expires when the
renewable TTL elapses and returns to normal Discovery eligibility.

## 13. Anti-anchoring rules

1. Portfolio, watchlist, and hypothesis overlap are context, not eligibility
   requirements.
2. Discovery screening runs over the full eligible point-in-time Discovery
   Universe before known-interest annotations are applied.
3. Active hypotheses may add comparisons or groups but cannot exclude assets,
   categories, contrary directions, or contradictory relationships.
4. Candidate predicates are identical for familiar and unfamiliar categories;
   known-interest overlap only determines whether a candidate is a new blind
   spot or a changed known phenomenon.
5. At least one downstream candidate lane remains available to `NONE`/`PARTIAL`
   overlap candidates; Task 3 priority then applies its frozen anti-anchoring
   and top-K rules.
6. No narrative label, analyst preference, or LLM output may alter deterministic
   candidacy.

Thus an active semiconductor thesis cannot suppress persistent, coherent
utility or electrical-infrastructure leadership. Conversely, the system does
not force an unrelated sector candidate merely to appear diverse.

### 13.1 Narrative-challenge evidence chain

Future Analyst enrichment that challenges an active hypothesis must preserve
the following attributable structure:

1. **Current hypothesis:** the explicit, versioned thesis being evaluated.
2. **Contradictory observations:** immutable candidate and event references.
3. **Evidence chain:** measurements, relationships, times, provenance, and
   relevant confirming or contrary evidence.
4. **Interpretation:** the proposed meaning of those observations.
5. **Alternative explanation:** at least one materially plausible competing
   account when available.
6. **Falsification conditions:** observable facts that would invalidate or
   materially weaken the interpretation.

Interpretation cannot replace the evidence chain. For example, persistent
utility/electrical-infrastructure relative-strength improvement, broader
participation, and stable credit while AI remains primary leadership may mean
that leadership is broadening; it does not deterministically mean that the AI
regime ended.

### 13.2 Structured news and catalyst boundary

Sentinel v0.1 discovery does not require news and must produce deterministic
results when no news or Analyst service exists. A future structured News/Event
Enrichment layer owns catalyst verification under versioned DX27 configuration.
That layer may help distinguish sector-driven behavior from company-specific
idiosyncratic behavior and must attach:

- catalyst identity and event type;
- affected subjects and groups;
- event timestamp;
- source and revision provenance;
- verification state and evidence basis;
- relationship to observed market behavior.

Versioned configuration defines approved source classes, provenance
requirements, verification states, and catalyst types. Authoritative or primary
sources are preferred conceptually, including company filings and
announcements, regulatory releases, earnings disclosures, and other formally
attributable events. Exact providers remain an implementation decision.

Structured catalyst data is supporting context, not a replacement for market
facts. GPT does not decide whether a catalyst is verified. Unverified media
reports, rumors, social posts, and unsupported GPT inference may assist the
separate Analyst Interpretation layer, but cannot satisfy deterministic
fast-path verification. GPT prose cannot establish verification, manufacture an
event, change candidate evidence, or satisfy the fast path by itself.

## 14. Discovery metrics

v0.1 should use a small set of understandable metrics:

- relative return versus a broad benchmark over declared windows;
- relative return versus a versioned parent sector/group;
- cross-sectional relative-rank state and material rank change;
- robust volume or traded-value percentile against a comparable baseline;
- realized-volatility-normalized price change;
- group participation fraction with observed-member coverage;
- group coherence based on aligned member direction/relative behavior;
- completed-session persistence state;
- count of independent members and evidence lineages.

No metric is universally required. Each discovery family defines its necessary
evidence. Percentiles, robust deviations, ranks, and state transitions must
name their baseline and sample requirements.

The model is not:

```text
DiscoveryScore = weighted sum of momentum, volume, and volatility
```

The normative evaluation is:

```text
quality gates
    -> family-specific deterministic predicates
    -> evidence vector
    -> novelty/persistence/coherence state
    -> candidate state and optional promotion
```

## 15. Relation to the Event Taxonomy

Discovery does not add event types. Its evidence uses the frozen primitives:

- unexpected leadership: `RELATIVE_STRENGTH_CHANGE`;
- abnormal activity: `ACTIVITY_ANOMALY`;
- participation: `PARTICIPATION_CHANGE`;
- coherence or contradiction: `RELATIONSHIP_CHANGE`;
- structural transitions: `PRICE_LEVEL_INTERACTION` and `TREND_CHANGE`;
- normalized rates, credit, USD, commodity, or other series changes:
  `SERIES_STATE_CHANGE`;
- volatility facts: `VOLATILITY_CHANGE`, following event-type precedence.

`DiscoveryCandidate.constituent_event_ids` references immutable events.
Candidate state cannot mutate their subjects, semantics, evidence, lifecycle,
or identity. When discovery screening precedes full event materialization, all
supporting facts must still be emitted through valid frozen detector semantics
before the candidate can proceed downstream.

## 16. Relation to the Priority Model

Discovery supplies structured context; it never classifies attention priority.
A supporting `DetectedEvent` may carry:

```text
relevance_context.is_discovered_outside_known_interest = true
```

and reference its candidate stream. The frozen Priority Model may use novelty,
scope, persistence, independent confirmation, and known-interest context to
produce a `PriorityItem`. It alone assigns `P0`, `P1`, `P2`, or `NOISE`.

Discovery evidence lineage must remain available so Task 3 can avoid counting
multiple derivatives of the same observation as independent confirmation.
Candidate promotion to Contextual monitoring neither guarantees visibility nor
changes priority classification.

## 17. Historical evaluation and survivorship bias

### 17.1 Determinism

Given identical:

- completed observations;
- point-in-time Discovery Universe version;
- point-in-time classification and group-membership metadata;
- known-interest snapshot and portfolio state;
- prior discovery state;
- discovery model version and configuration;

the system must produce identical candidates, candidate IDs, states,
promotions, expiries, and canonical ordering.

Historical evaluation uses only information knowable at each replay step.
Future bars, later portfolio state, later candidate state, and later membership
cannot affect an earlier decision.

### 17.2 Point-in-time membership

Using today's index, sector, or security list in an older replay creates
survivorship and classification bias. Delisted, acquired, failed, or reclassified
members would be omitted, while future successful constituents would be
incorrectly included.

Therefore:

- replay must bind a point-in-time universe and membership version to each scan;
- membership effective dates and revisions must be preserved;
- absent historical membership gates group/participation evaluation as
  unavailable rather than substituting current membership;
- results produced from an explicitly declared static research universe must be
  labeled non-point-in-time and cannot be used as unbiased acceptance evidence.

`HistoricalReplay` remains unchanged and provides completed immutable prefixes;
Discovery consumes that behavior rather than creating a second replay engine.

## 18. Configuration and version identity

Every run records:

- `discovery_model_version`: semantic version of the discovery architecture and
  state-machine meaning;
- `discovery_config_id`: deterministic digest of canonical effective
  configuration;
- `source_universe_version`;
- classification and group-membership versions;
- prior-state snapshot identity.

The configuration digest covers at least:

- subject eligibility and quality gates;
- allowed group sources and canonicalization;
- observation-granularity modes and transition predicates;
- family-specific predicates and metric definitions;
- baseline and sample requirements;
- novelty and persistence rules;
- single-name exception rules;
- promotion, reevaluation, cooldown, and expiry rules;
- normal/fast promotion paths and the renewable Contextual TTL;
- `FAST_PATH_SUPPORTED`/`FAST_PATH_ENABLED` capability state and approved
  catalyst-source policy;
- default and category-specific Contextual TTL policy;
- canonical ID and ordering semantics.

Changes to architecture/state semantics change `discovery_model_version`.
Changes to effective thresholds, windows, group mappings, gates, or transition
rules change `discovery_config_id`; a change may require both. Human-readable
labels and comments that do not affect output need not change identity.

Changing an approved catalyst source class, fast-path enablement, granularity
mode, automatic-transition policy, default TTL, or category-specific TTL policy
must change `discovery_config_id`.

Canonical serialization must define field order, set sorting, timezones, number
representation, missing values, and hashing. Same inputs, state, and identities
must yield the same results.

## 19. Worked examples

### 19.1 Unknown utility sector begins persistent leadership

- **Candidate:** Yes, after valid daily relative leadership persists and utility
  participation/coherence confirms.
- **Promotion:** Yes, if `PERSISTENT_LEADERSHIP` and
  `MULTI_MEMBER_COHERENCE` predicates hold; activation is time-bounded.
- **Events:** `RELATIVE_STRENGTH_CHANGE`, `PARTICIPATION_CHANGE`, and possibly
  `RELATIONSHIP_CHANGE`.
- **Noise control:** One strong utility or one session is insufficient; group
  membership, coverage, and completed-session persistence are required.

### 19.2 Five electrical-infrastructure stocks strengthen together

- **Candidate:** Yes, as one canonical economic-group candidate when the curated
  group version and member coverage are valid. Member candidates may also form
  under configured `GROUP_AND_MEMBERS` granularity when their trajectories are
  materially distinct.
- **Promotion:** Yes when multi-member coherence plus leadership or structural
  confirmation satisfies promotion.
- **Events:** group `RELATIONSHIP_CHANGE`, member/group
  `RELATIVE_STRENGTH_CHANGE`, `PARTICIPATION_CHANGE`, and synchronized
  `TREND_CHANGE` where applicable.
- **Noise control:** Common movement collapses into the group candidate; distinct
  member candidates require residual/idiosyncratic evidence, and shared lineage
  is not counted five times as independent confirmation.

### 19.3 One random liquid stock rises 18% on extreme volume

- **Candidate:** Normally no. A candidate is possible only through the strict
  member-exception predicate or a verified catalyst plus market evidence.
- **Promotion:** No under the observed facts alone; the fast path would require a
  verified material catalyst and strong market confirmation.
- **Events:** Valid `PRICE_GAP`, `PRICE_LEVEL_INTERACTION`,
  `ACTIVITY_ANOMALY`, or `VOLATILITY_CHANGE` may still exist.
- **Noise control:** No persistence, peer/group confirmation, or unique
  structural economic role satisfies the single-name exception.

### 19.4 Semiconductors remain strong with no material change

- **Candidate:** No new candidate; the existing stream is `PERSISTING` with
  novelty `UNCHANGED` if still active.
- **Promotion:** No new activation or extension solely from repetition.
- **Events:** Continuing `RELATIVE_STRENGTH_CHANGE` streams may remain valid.
- **Noise control:** New event occurrences and repeated rank do not constitute
  novelty or strengthening.

### 19.5 Previously ignored industry shifts from weak to strong

- **Candidate:** Yes when a material relative-rank/state transition persists and
  multiple members confirm.
- **Promotion:** Yes after confirmation, with `PERSISTENT_LEADERSHIP` or
  `STRUCTURAL_TRANSITION` as the reason.
- **Events:** `RELATIVE_STRENGTH_CHANGE`, `TREND_CHANGE`, and valid
  `PARTICIPATION_CHANGE`.
- **Noise control:** A single daily rank jump or incomplete membership does not
  qualify.

### 19.6 A discovered candidate becomes a portfolio holding

- **Candidate:** The existing immutable candidate history remains; its current
  known-interest overlap becomes `DIRECT`.
- **Promotion:** Discovery-originated activation may be superseded by the
  holding-owned monitoring reason without duplication.
- **Events:** Existing primitive events remain unchanged; later events carry
  current relevance context.
- **Noise control:** Holding status does not create a second candidate or reset
  novelty.

### 19.7 Candidate loses leadership and expires

- **Candidate:** A final state snapshot becomes `WEAKENING` or `RESOLVED`, then
  expires under configuration.
- **Promotion:** Discovery-originated Contextual activation ends; unrelated
  activation reasons remain.
- **Events:** `RELATIVE_STRENGTH_CHANGE` weakening/reversal and possibly
  `PARTICIPATION_CHANGE` deterioration.
- **Noise control:** Old evidence cannot preserve activation; loss of structure
  may demote before the 30-day TTL, and a cooldown prevents immediate
  oscillating recreation.

### 19.8 Existing AI thesis contradicted by an emerging sector

- **Candidate:** Yes for the unrelated sector when its own predicates hold,
  despite the active AI hypothesis.
- **Promotion:** Yes if persistent/coherent; `MATERIAL_CONTRADICTION` may be an
  additional reason when the relationship is explicit.
- **Events:** emerging-sector `RELATIVE_STRENGTH_CHANGE` and participation;
  cross-theme `RELATIONSHIP_CHANGE` where valid.
- **Noise control:** The contradiction must be measured, not inferred from a
  narrative; the hypothesis cannot filter it out.

### 19.9 Broad rally with only one narrow group participating

- **Candidate:** Potentially yes for the narrow group and/or narrowing market
  structure, subject to reliable membership.
- **Promotion:** The group may promote after persistence; the broader condition
  proceeds to Priority independently.
- **Events:** group `RELATIVE_STRENGTH_CHANGE`, market/group
  `PARTICIPATION_CHANGE`, and `RELATIONSHIP_CHANGE` for breadth divergence.
- **Noise control:** Index return alone is insufficient, and unavailable breadth
  prevents a breadth claim.

### 19.10 Multiple unrelated sectors emerge simultaneously

- **Candidate:** Yes, one canonical candidate per independently qualifying
  economic phenomenon.
- **Promotion:** Each is evaluated by the same predicates; no forced one-per-
  sector quota applies.
- **Events:** distinct relative-strength, participation, relationship, and
  activity events for each sector.
- **Noise control:** Correlated instruments collapse within their groups, while
  unrelated evidence is preserved rather than combined artificially.

### 19.11 Discovery based on incomplete group membership

- **Candidate:** No group candidate when coverage or membership-version gates
  fail.
- **Promotion:** No.
- **Events:** Valid single-subject events may remain, but no
  `PARTICIPATION_CHANGE` or group-coherence claim is fabricated.
- **Noise control:** Missing members are metadata, never votes for unchanged or
  normal behavior.

### 19.12 Historical replay with current constituents

- **Candidate:** Not accepted as unbiased discovery if only current constituents
  are available for the historical date.
- **Promotion:** None in acceptance evaluation; the scan is gated or explicitly
  labeled a non-point-in-time research result.
- **Events:** Subject-level events may be replayed where their own history is
  valid, but group participation/coherence is unavailable.
- **Noise control:** Current winners cannot leak backward into the historical
  universe, and missing failed/delisted members cannot be silently ignored.

## 20. Explicit exclusions

Sentinel v0.1 Blind-Spot Discovery does not include:

- a largest-gainer, highest-volume, or highest-volatility leaderboard;
- social-media, news, rumor, or narrative ingestion as a required v0.1 input;
- LLM-based raw facts, deterministic grouping, discovery scoring, candidacy, or
  priority assignment;
- implementing the future GPT Analyst or structured news/catalyst integration;
- a weighted black-box discovery score;
- a new market-event taxonomy;
- `P0`/`P1`/`P2` assignment or changes to the Priority Model;
- the final `SentinelReport` contract;
- trade recommendations, `BotSignal`, targets, orders, or execution;
- dynamic portfolio, risk, approval, or strategy actions;
- automatic parameter optimization;
- unsupported inferred sector/industry/supply-chain classifications;
- full global-market, options-chain, futures-curve, or crypto discovery;
- intraday Discovery Universe scanning in v0.1;
- permanent watchlist or Contextual growth;
- treating proxy observations as authoritative economic series;
- using future observations or current constituents in historical scans.

## 21. Invariants

1. Discovery is deterministic.
2. Discovery does not trade.
3. Discovery does not assign `P0`, `P1`, or `P2`.
4. Discovery does not invent new event types.
5. Discovery may surface areas outside portfolio and watchlist interests.
6. Known interests cannot suppress contradictory discoveries.
7. Single-name noise is strongly controlled.
8. Evidence-appropriate group/member granularity is preferred over random
   movers.
9. Missing or invalid data cannot create or strengthen a discovery.
10. Discovery does not permanently expand the universe.
11. Repetition without material new information does not increase candidacy.
12. Same completed inputs, state, metadata, and configuration produce the same
    result.

## 22. Open questions before design freeze

### 22.1 Remaining owner-level decisions

Task 4 has no unresolved owner-level decisions. The fast-path capability and
initial gating, user-visible Analyst boundary, versioned catalyst-verification
ownership, configuration-driven v0.1 granularity, and renewable 30-day default
TTL are frozen design decisions in this proposal.

### 22.2 Engineering and implementation-design questions

1. What exact liquidity, price, and history thresholds instantiate the frozen
   Discovery Universe eligibility rules?
2. Which point-in-time security master and classification source will be
   authoritative?
3. Which manually curated economic-role groups are permitted before that source
   exists, and who versions them?
4. What minimum member count and coverage fraction validate each group kind?
5. Which relative-return windows and robust rank-transition methods are allowed
   initially?
6. What volume/traded-value baseline correctly handles daily seasonality and
   corporate events?
7. Which coherence measure is simplest while remaining robust to one dominant
   member?
8. What exact temporal predicate confirms persistence, and how may holidays or
   missing sessions interrupt it?
9. Which same-cycle cross-sectional evidence can form a `NEW` candidate before
   temporal confirmation?
10. How are material `STRENGTHENING`, `WEAKENING`, and `CHARACTER_CHANGED`
    transitions mapped for each discovery family?
11. What canonical benchmark and parent group apply to every eligible subject?
12. What objective market-significance class permits the single-name exception?
13. How are pump-like isolation and unresolved corporate actions identified
    without a news feed?
14. What cooldown and maximum-age rules apply to candidate streams and promoted
    activations?
15. How do multiple independent activation reasons compose and expire without
    removing monitoring required by holdings or watchlists?
16. What exact metadata distinguishes an active hypothesis's subject coverage
    from its prose description?
17. Which authoritative cross-asset inputs and proxies are accepted in v0.1?
18. How is candidate evidence lineage represented so Task 3 can evaluate
    independent confirmation identically?
19. What canonical serialization and digest algorithm define IDs and config
    identity?
20. How are restatements, symbol changes, mergers, and classification revisions
    represented in historical state?
21. What behavior is required when point-in-time membership exists for only part
    of an evaluation period?
22. Which fixtures demonstrate anti-anchoring, no future leakage, deterministic
    expiry, and single-name suppression?
23. What acceptance metrics measure useful blind-spot recall without rewarding
    candidate volume or hindsight?
24. Where is candidate state persisted while keeping `HistoricalReplay` and
    primitive events immutable?
25. What schema-compatibility guarantees apply after v0.1?

## Status

DESIGN BASELINE — FROZEN FOR SENTINEL V0.1

Further substantive changes require an explicit, versioned design revision.
