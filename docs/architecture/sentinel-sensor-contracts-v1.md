# 6B-2G — Multi-Sensor Contracts & Validation Protocol v1

Status: **FROZEN 6B-2G DESIGN AND RESEARCH PROTOCOL**.
The [6B-2H runtime](sentinel-market-state-runtime.md) now implements the state
subset with fixture conformance. This specification and its locked protocol
remain the original design contract, not an operational/effectiveness approval.
The normative machine-readable registry is
[`protocol.json`](../../research/sentinel/6b-2g-contracts/protocol.json).
The [lock](../../research/sentinel/6b-2g-contracts/protocol_lock.json) identifies
its exact bytes and canonical content. This task freezes contracts, not a claim
of effective detection. 6B-2H is a separate implementation checkpoint.

## 1. Scope and registry

First scope: daily US equity state with volatility, credit, rates and funding
context. This is not global market health. The registry assigns eight Core
feed roles (SPY, RSP, QQQ, IWM, VIX, high-yield OAS, 2Y and 10Y Treasury yields)
and eleven optional Contextual roles (nine sector ETFs, SOFR and EFFR).
These are the first research subset, not a replacement for the wider Core
budget or a completed universe population. Existing four-tier contracts remain.

| Measurement | Meaning / unit | Role and redundancy |
| --- | --- | --- |
| SPY and RSP 20-session log returns | Cap-weighted and equal-weight basket direction | RSP is a proxy for participation; both equity-price lineage. |
| QQQ/SPY, IWM/SPY 20-session relative log returns | Leadership/style differences | Proxies, not Mega-7 or the S&P 500 remainder. |
| RSP/SPY 20-session relative log return | Internal weighting divergence | Participation proxy, not constituent breadth. |
| SPY RV20 and RV5/RV20 | Realized variability / ratio | Same equity-price input; volatility redundancy group. |
| VIX level | SPX approximately 30-day implied volatility, percent annualized | Authoritative series only through a verified binding. |
| VIX minus SPY RV20 | Percentage-point implied/realized gap | Horizon mismatch; not a true variance risk premium. |
| HY OAS | US high-yield option-adjusted spread, basis points | Credit; HY ETF returns cannot substitute for this series. |
| 2Y, 10Y and 10Y–2Y | Yield percent per annum / slope basis points | Rates, not automatically equity pressure. |
| SOFR–EFFR | Basis-point funding context | Optional; not automatically a stress threshold. |
| Nine sector/SPY relative returns | Vector of leadership proxies | Optional, sorted vector; correlated sectors are not nine confirmations. |
| PIT constituent breadth, top-seven weight, Mega-7 contribution | True internal participation/concentration | BLOCKED until historical membership/weights and accounting are validated in a new protocol version. |

The nine sector roles are XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU and XLB.
No modern sector history is fabricated. A missing sector prevents a complete
nine-member vector; usable individual members may remain visible as partial
context without producing a complete rank or independent votes.

Stable source-role IDs in this registry are not substitutes for canonical
`SubjectRef` instrument identities. 6B-2H binds them to versioned identities,
provider series, unit conversion and validation records. No source becomes
operational solely by appearing here. Yahoo may supply ETF/index research data;
it does not certify historical availability or economic-series vintages.
Candidate economic bindings include ICE BofA US HY OAS (FRED
`BAMLH0A0HYM2`, percent converted to basis points), Treasury `DGS2`/`DGS10`,
and official SOFR/EFFR. These bindings require metadata verification before use.

Daily return uses a versioned total-return-consistent price chain with corporate
actions known at cutoff. Latest adjusted historical prices are admissible only
for explicitly descriptive retrospective research if their original vintage is
unknown. Production/confirmation cannot use future adjustments silently.
RV uses sample standard deviation (`ddof=1`), 252 annualization, and 20 completed
session-to-session log returns from 21 price observations. Endpoints include
the current completed session; a normalization baseline excludes it.
Relative measurements use identical session endpoints. A return window must
have consecutive required sessions; missing bars are not compressed into a
shorter effective window. Invalid prices are SOURCE_ERROR; a zero denominator
or zero MAD is INSUFFICIENT_HISTORY, never infinity or a fabricated score.

## 2. Availability and time contract

Use a versioned XNYS session calendar, including holidays, DST and early closes.
Decision cutoff is **actual session close + 120 minutes**, stored in UTC;
`America/New_York` defines session boundaries. This is a fixed daily observation
schedule, not an execution timestamp. The existing weekday intraday replay
calendar is insufficient; 6B-2H must add or supply this calendar behind existing
replay/application boundaries rather than claim it already exists.

A normalized point distinguishes:

- `observation_window`: the completed economic/trading period the value describes;
- `published_at`: independently evidenced source publication time, nullable;
- `first_seen_at`: the time this source revision was actually recorded, required;
- `available_at`: `max(published_at, first_seen_at)` when publication is known,
  otherwise `first_seen_at`. Never infer historical availability from a date.

At cutoff t, only a revision with `available_at <= t` may enter measurements,
including all warmup/baseline points and corporate-action inputs. Use the latest
eligible revision, tie-break by source revision sequence; ambiguous conflicting
versions are SOURCE_ERROR. Previously emitted snapshots stay immutable;
corrections appear in later snapshots with revision lineage.
Historical vintage archives may provide evidenced original capture times;
a present-day fetch without those records has a present-day first-seen time.
Consequently it cannot pass causal historical replay just by assigning an
assumed release delay. Descriptive-only historical mode is explicit and cannot
pass prospective confirmation. Freeze dataset/vintage/calendar manifests.

ETF points must describe the current session (maximum age zero). Index/economic
points may be at most one completed XNYS session old, retain their actual
observation timestamp and carry `LAGGED_INPUT` when old. Publication frequency
and source holiday differences are disclosed. Beyond the bound, STALE and no
current asserted value. Never forward-fill prices, interpolate missing sessions,
combine mismatched observation dates for a spread, or relabel delayed data as
current. Derived freshness is the strictest of required input policies.
For optional pressure/divergence references, all constituent measurements must
describe the current session; lagged level context can still be shown separately.

The existing `DataStatus` enum is reused without extension. Eligibility faults
use deterministic precedence: SOURCE_ERROR, UNSUPPORTED_SESSION, UNAVAILABLE,
STALE, INSUFFICIENT_HISTORY, AVAILABLE. Field-level reason codes preserve other
faults. A known not-yet-published source is UNAVAILABLE, not SOURCE_ERROR.
Unknown point values stay null. An optional last-known diagnostic, if added
later, must be separate and cannot occupy a current `value` field.

## 3. Frozen output contracts

Registry `contracts` defines the exact required field names. These are design
contracts, not implemented Python types. Lists with set semantics are sorted
and deduplicated before canonical hashing; vectors sort by canonical subject ID.
All numeric values are finite, all timestamps timezone-aware UTC, all IDs and
versions nonempty. Unknown values use JSON null, not omission of required fields.
The full input/source/configuration lineage participates in content identity.

### SensorDescriptor v1

`subject_refs` are canonical `SubjectRef` values. `proxy_for` is required text
for PROXY, null for DIRECT. `source_binding_version` identifies role-to-provider
mapping or is null when unbound. Units, method, lookback, redundancy group and
activation match the registry; a descriptor change produces a new version.
DIRECT means direct measurement of its specified object, not a claim that the
object represents the whole market. Proxy/direct status never implies evidence
independence: lineage must be shared for common source observations.

### SeriesPoint v1

Reuse `SubjectRef`, `ObservationWindow`, `DataStatus` and source attribution
semantics; add publication/capture/revision timestamps without reinterpreting
`Provenance.observed_at` as publication. `value` is a finite scalar when AVAILABLE,
otherwise null. `payload_sha256` pins the source payload; `revision_id` and
`source_version` identify immutable input versions. `vintage_mode` is either
`RECORDED_AS_AVAILABLE` or `LATEST_VINTAGE_DESCRIPTIVE_ONLY`.
OHLCV continues through `ObservationEnvelope`/`MarketContext`, with the same
availability sidecar metadata. Do not force a scalar economic series into that
OHLCV envelope or create a second market-data/replay engine.

### SensorMeasurement v1

`value` is a finite scalar, or the explicitly typed sector vector, only when
AVAILABLE. `available_at` is the maximum availability of all required input
points. `observation_window` spans actual contributing observations.
`reliability` contains `usable_points`, `required_points` and
`validation_record_id` (nullable); sample support is not a probability of truth.
`input_point_ids` and `lineage_ids` must resolve to snapshot-pinned inputs.
Each unavailable sensor remains represented, with null value and reasons.
BLOCKED_PIT_INPUTS sensors always produce UNAVAILABLE in this version.

### MarketStateSnapshot v1

`dimensions` is a sorted collection of seven dimension records, each with
`dimension_id`, `data_status`, `measurement_ids`, `required_measurement_ids`,
`qualifiers`. `relationships` references the relative, slope, implied/realized
and optional funding measurements; it does not assert relationship change merely
because a level is unusual. No global directional regime is inferred.
`coverage` contains expected/available counts for registered, active-required,
optional and blocked sensors plus an explicit coverage grade
COMPLETE/PARTIAL/UNAVAILABLE. This grade is not a new DataStatus.

A dimension is AVAILABLE only when its active-required measurements are all
available. Participation with only RSP/SPY carries `PROXY_ONLY` and
`TRUE_BREADTH_UNAVAILABLE`; it cannot claim constituent breadth. Funding is
UNAVAILABLE when its optional measurement is absent. Snapshot `data_status`
is AVAILABLE if all active-required measurements across dimensions are
available, even if optional/blocked measurements are unavailable. Coverage
must still disclose those gaps. Otherwise aggregate required-input failures
using the precedence in section 2; usable dimensions remain visible.
`protocol_digest` pins this exact registry. Schema, cutoff, effective inputs,
calendar/vintage/configuration versions and sorted measurements determine
`snapshot_id`; processing wall time, visit history, holdings and Analyst text do
not. Rebuilding the same prefix produces the same facts and identity.

### CompositeReference v1

A research attachment with exact named configuration, not Priority or a
probability. `value` is finite only when AVAILABLE. `group_contributions` records
ordered named weighted terms summing to S (absolute tolerance 1e-10) or named
unweighted D component values with the selected maximum. `delta` is null unless
the immediately prior XNYS snapshot has an available same-config reference.
No interpolation across missing snapshots. `coverage` states required and
usable inputs, even for unavailable results. Operational output stays disabled
until 6B-2I passes; state/event reporting does not depend on it.

### ConditionalForecast v1

Future-oriented optional research attachment. Enabled forecasts require a
nonempty validation record, model/calibration versions, explicit target and
horizon, causal input refs, and a finite probability in [0,1]. `data_status`
AVAILABLE is prohibited without a passing validation record. The default report
contains no forecast attachments. A disabled research stub is UNAVAILABLE,
value null, qualifier `NOT_VALIDATED`; it is not a zero-risk prediction.
The contract must carry `qualifiers` for this stub; it is listed in the registry.

Existing `DetectionResult` and `DetectedEvent` contracts are retained. AVAILABLE
with no events means evaluated/no trigger; unavailable is not a normal non-event.
No new event primitive, trading signal, or execution semantics is introduced.

## 4. Simple reference candidates frozen for 6B-2I

Pressure baseline `us-equity-pressure-3g-v1` has three groups, each weight 1/3:

1. Equity weakness: mean inverse percentile of SPY and RSP return20.
2. Volatility: mean percentile of SPY RV20 and VIX.
3. Credit: HY OAS percentile.

`S = 100 * sum(weight * group_score)`. This is an explicitly limited equity
pressure reference; it excludes rate/funding/true-breadth dimensions and must
not be called a comprehensive financial-stress index. Prior baseline is the
last 252 XNYS sessions, excluding current, requiring 126 usable measurements
that were current-session observations at their original snapshot cutoffs. Use midrank empirical percentile; no stale observations or
forward-filled repeats. Missing any current required measurement or baseline
support yields unavailable, with no weight redistribution.

D baseline `us-equity-divergence-2p-v1` is the maximum absolute causal robust z
of RSP/SPY and QQQ/SPY return20, each using prior-session median and
`1.4826*MAD` with the same 252/126 history policy. D measures unusual divergence,
not average pressure, directional prediction or all cross-asset relationships.
There is no combined S+D number. CISS-style correlations, covariance inversion,
learned weights and dynamic factors require separate pre-registration, not
result-driven addition to this baseline.

## 5. Validation protocol and prospective separation

Observed 2005–2026-09-30 data may be reused for disclosed development and
retrospective audit, never as a newly untouched holdout. Development fitting
uses through 2019; 2020 onward is already-observed audit evidence. Future
confirmation starts the first full XNYS session after the final candidate
protocol commit, not after this architectural document alone. Freeze candidate
code/configuration, bindings, target definitions and dataset manifest before
confirmation. Require at least 252 decision sessions plus complete outcome
followup; sample-count requirements may demand longer. No arbitrary deadline
converts sparse evidence into PASS. Candidate changes restart confirmation
under a new version; do not cherry-pick start dates or reuse evaluated outcomes.

6B-2H validates current-state fidelity, not predictive accuracy: independent
formula calculations, coherent units, complete lineage, causal availability,
missing/proxy handling, and deterministic prefix replay. Require zero causal,
identity, imputation or mislabelling violations, numerical agreement within
1e-10, and at least 95% required-feed operational coverage over the declared
sample. Insufficient live support prevents operational promotion; fixture checks
can still validate implementation correctness. G checks only the frozen design.

### Independent change targets for 6B-2J

Targets use completed future observations only in evaluation, never in online
features. They are explicit statistical surrogate targets, not universal ground
truth for economically important changes. Each anchor t uses previous 20 returns
ending at t, with sample standard deviation sigma. Zero sigma, missing sessions,
or unavailable future outcomes make the label unscorable and disclosed.

- **Trend shift**, SPY and RSP separately: prior20 mean and both successive
  future20 means have opposite signs; each absolute mean is at least
  `sigma/sqrt(20)`. Direction is the future sign. Followup 40 sessions.
- **Volatility shift**, SPY: both successive future5 sample-RV/prior20 sample-RV
  ratios are >=1.5 (increase), or both <=2/3 (decrease). Followup 10 sessions.
- **Relationship shift**, RSP/SPY and QQQ/SPY separately: use daily return
  spread, not the detector's 20-day cumulative signal. Both future10 means
  differ from prior20 mean in the same direction by at least
  `2*sigma/sqrt(10)`. Followup 20 sessions.

Greedily retain the earliest eligible label anchor per subject/family, regardless
of direction; suppress subsequent anchors for its followup length. No backward
refinement to a favourable change date. Sort anchors chronologically and match
the earliest unused alarm of the same subject, family and direction in [t,t+5].
Every alarm and target match at most once. Earlier alarms receive no retroactive
credit. Alarm cooldown is five sessions per subject/family, regardless of
direction, with the first alarm retained; raw suppressed alarm counts remain
reported. Events map to TREND_CHANGE, VOLATILITY_CHANGE and RELATIONSHIP_CHANGE.
True participation labels stay blocked until PIT inputs and a versioned target
exist; a relationship proxy cannot masquerade as PARTICIPATION_CHANGE.

Eligible scored sessions have complete label followup. Detector abstentions on
those sessions remain in the missed-target denominator; availability is reported
separately. Missing future label data is disclosed as unscorable, not a negative.
Precision = matched alarms / scored alarms; recall = matched targets / scorable
targets; F1 = harmonic mean; delay is matched alarm session minus anchor session;
unmatched alarm rate = unmatched/scorable decision sessions * 252. Zero
metric denominators produce insufficient evidence, not perfect scores.

Baselines are NO_CHANGE, frozen causal thresholds, and the archived EWMAC
64/256 state transitions as a research comparator. Fixed thresholds use return20
mean divided by prior20 daily sigma times sqrt(20), crossing +/-2; RV5/RV20
crossing 1.5 or 2/3; daily spread5 mean minus prior20 mean divided by
prior20 sigma/sqrt(5), crossing +/-2. Baseline normalization uses history before
its current five-/twenty-session measurement; full definitions are registered
under `baseline_definitions`. Crossings require the prior completed evaluation
to be on the non-trigger side; unavailable gaps break crossing continuity.
EWMAC follows the archived method/version and first available directional
state transitions without changing parameters. NO_CHANGE emits no alarms and
has undefined precision when no alarms; it is a recall/false-alarm control,
not a candidate that can pass the precision gate.

For each target/subject/direction independently, require at least 30 labels,
precision and recall >=0.60, median delay <=3 and p90 <=5, unmatched alarms
<=12 per 252 scorable sessions, availability >=0.95, and absolute F1 improvement
>=0.05 over fixed thresholds, with positive 95% block-interval lower bound.
Pooled results cannot rescue a failed stratum. If a baseline has no alarms,
its F1 is defined as zero for paired improvement only; its precision remains
undefined. A candidate can be promoted only for passing declared strata, with
failed/insufficient strata explicitly disabled; no blanket market-wide claim.

Use 40-session moving-block bootstrap, 1,000 replicates, seed 627, resampling
all subjects jointly. Score/match full chronology once, then resample session
sufficient statistics (TP/FP/FN/availability); never rematch across artificial
block joins. Reference/forecast intervals resample the paired fixed-grid
outcomes and prediction scores in calendar blocks, preserving pairings.
Use percentile 2.5/97.5 bounds. Quantiles use linear interpolation.
Purge 40 sessions of anchors before evaluation boundaries and embargo the next
40 when a training block follows evaluation. Outcome windows never cross split
boundaries. All subjects share calendar cutoffs; warmup only uses eligible past.

### Reference and forecasting gates

6B-2I first tests whether S/D add information to the dimension vector for
SPY's next-20-session maximum close-to-close drawdown >=5%. This is drawdown
from the running peak including the anchor close, not terminal return or
intraday low. Use nonoverlapping 20-session anchors, starting at the first
eligible declared confirmation session; keep the fixed grid when data is missing.
Compare a frozen development-fit logistic model using the causal scalar
active-required dimension measurements with the same model plus S and D.
Require AUC increment >=0.02 with a positive 95% block-interval lower bound,
and at least 30 positive and 30 negative complete outcomes. Extra deterministic
transforms need not add information; a zero gain is a valid result, not a reason
to introduce a more complex score. Report leave-one-sensor-out and +/-20%
relative group-weight sensitivity without selecting a new winner from these
checks. Reference gate success does not enable forecasts or Priority scoring.

6B-2K separately requires Brier skill >=0.05 against both development-frequency
and development-fit RV20/VIX logistic baselines, positive 95% lower bounds,
>=30 positive/negative nonoverlapping outcomes, and equal-width five-bin expected
calibration error <=0.05. These numerical gates are engineering research
acceptance choices, not literature-established market laws. Model family,
regularization and fitting details must be locked in 6B-2I/K before any
prospective run; open candidate fitting details cannot be used as an OOS
selection loophole. Default output remains disabled.

Decision vocabulary: PASS, FAIL, INSUFFICIENT_EVIDENCE, BLOCKED_DATA. Integrity
violations force FAIL; absent usable inputs give BLOCKED_DATA; inadequate counts
or undefined required metrics give INSUFFICIENT_EVIDENCE; evaluable numeric gates
that fail give FAIL. No WEAK_PASS is sufficient for operational promotion.

## 6. Explicit SentinelReport design revision v0.2

The frozen v0.1 required containers, MarketNow/PortfolioNow peers, event
projection, P0 visibility, top-K rules, TWR and Analyst boundaries remain.
This version adds three optional fields inside `MarketNow`:

- `state_snapshot_ref`: exact snapshot ID/schema/protocol digest, nullable;
- `reference_values`: typed CompositeReference attachments, default [];
- `conditional_forecasts`: typed ConditionalForecast attachments, default [].

Dimension states project into existing MarketNow component slots using their
StateValue status/as-of/evidence pattern. Proxy participation qualifiers and
true-breadth gaps are required; no unqualified whole-market label. Optional
references and forecasts participate in deterministic report identity when
present; Analyst text remains separately identified. Consumers must negotiate
v0.2 when reading these fields; absence does not break v0.1 consumers.
No report implementation, UI, portfolio change or new priority predicate is
part of 6B-2G.

## 7. Verification and handoff

The offline protocol validator checks finite JSON, registry IDs/references,
units, method coverage, causal/missing-data policies, target followups/split
boundaries, reference group weights and member orientation, disabled future
outputs, and exact lock integrity. Negative tests reject protocol mutations
that would admit lookahead, proxy breadth, hidden reweighting or premature
forecasting. This validates the design artifact; it does not test a nonexistent
runtime's correctness or establish market effectiveness.

6B-2H must implement the typed scalar/availability bridge, descriptors,
measurements, calendar-aware state snapshot and report projection fixtures.
Acceptance includes future-published/captured data rejection; late/revised
series; stale/missing/equal-window inputs; DST/holiday/early-close sessions;
PIT-blocked features; partial sector context; contradictory SPY/RSP states;
input-order invariance and prefix replay with unchanged prior identities.
Keep S/D operational calculation, detectors and forecasts outside that task.
Proceed only to the next numbered checkpoint after review of this one.

## Literature linkage and 6B-2I research checkpoint

The [versioned bibliography sidecar](../../research/sentinel/references/README.md)
associates all 18 sensor contracts and 19 feeds with stable reference IDs, pinning
this exact protocol digest. Runtime descriptor annotations also carry the
descriptor/library/mapping versions. It does not rewrite the frozen protocol or
change Descriptor v1 fields. Source definitions, local formula choices, and
validation evidence have separate provenance. See the
[6B-2I implementation checkpoint](sentinel-composite-reference-research.md);
real source admission and incremental effectiveness remain blocked.
