# 6B-2H — Multi-Dimensional Market State Snapshot

Status: **RUNTIME IMPLEMENTATION; FIXTURE CONFORMANCE CHECKPOINT**.
Live provider coverage and market effectiveness are separate, unpassed gates.
This task implements the [frozen 6B-2G contracts](sentinel-sensor-contracts-v1.md)
without changing its locked protocol, reference formulas or acceptance thresholds.

## Runtime path

```text
validated source binding + recorded publication/capture metadata
    -> existing ObservationEnvelope/MarketContext or normalized scalar series
    -> SeriesPoint, with immutable input/source/revision identity
    -> MarketStateBuilder using a pinned XNYS schedule and registry
    -> SensorMeasurement + seven DimensionState records
    -> MarketStateSnapshot and resolvable StateBuild evidence
    -> deterministic MarketNow v0.2 projection
```

Sentinel performs no provider I/O. The XNYS adapter uses pinned
`exchange-calendars==4.13.2`, materializes explicit start/end bounds, and hashes
source/version, bounds and all actual open/close timestamps into calendar identity.
Out-of-bounds/non-trading decision dates fail rather than guessing. A schedule
includes DST, holidays, early closes and extraordinary closures covered by its
rule version. A new rule package or schedule is a new identity; retained prior
snapshots are not rewritten. The domain does not import this third-party library.

The implementation is exported through `dx27.intelligence.sentinel`:
`FeedBinding`, `AvailabilityStamp`, `SeriesPoint`, `SensorDescriptor`,
`SensorMeasurement`, `SensorRegistry`, `MarketStateBuilder`, `MarketStateSnapshot`,
`StateBuild`, the normalization helpers, and `project_market_now`.

## Source and scalar bridge

`FeedBinding` is an immutable application-supplied metadata record with source
and canonical subject identity, units, validation-record ID/time, price basis,
source calendar, observation-label policy, and revision ordering. Its content
hash becomes the binding version. It does not certify its own assertions:
metadata validation must actually occur outside Sentinel. Fixture bindings use
explicit `fixture-only` validation IDs; no real provider is approved by this task.
Bindings validated after a decision cutoff are unavailable at that cutoff.

Approved unit conversions are identity and percent/percent-per-annum to basis
points (*100); arbitrary scales are rejected. Nonfinite/bool/string raw numbers
become SOURCE_ERROR with null value. Negative Treasury yields are valid numeric
context; nonpositive prices and negative VIX/HY OAS are invalid domains.

ETF close normalization reuses the existing OHLCV envelope, matching source
provenance and actual daily session bounds and checking OHLCV validity.
The binding must identify a total-return-consistent price chain as available,
not raw closes across undisclosed dividends/splits. The caller must establish
that corporate-action/vintage metadata; the bridge cannot infer it from prices.
Scalar economics/index values remain scalar series, never fake OHLCV bars.

## Observation dates differ from publication times and trading hours

ETF bindings require `source_calendar_id=XNYS` and `XNYS_SESSION` label policy.
Other sources declare their validated calendar and one of:

- `LOCAL_DATE_OF_END`: actual observation period ends within its stated New York
  date; supports a same-day index observation completed after stock close.
- `LOCAL_DATE_BEFORE_EXCLUSIVE_END`: complete midnight-to-midnight New York
  source day, labelled by the preceding date; DST can change elapsed hours.
- `UTC_DATE_BEFORE_EXCLUSIVE_END`: complete midnight-to-midnight UTC source day,
  labelled by the preceding date.

No economic point is silently shifted onto the stock session window. A source
may report on an XNYS holiday when its own validated calendar permits it.
Age counts completed XNYS sessions strictly after that source observation date;
`SOURCE_NON_XNYS_DATE` and `LAGGED_INPUT` disclose the difference. Pairwise
spreads require the same source observation date, not identical clock times.

Every consumed point must have a completed period and
`max(published_at,first_seen_at) <= decision_cutoff`. A present-day fetch cannot
be assigned an earlier first-seen time. If an AVAILABLE point purports to have
been captured/published before its period completed, it is SOURCE_ERROR.
The first-seen timestamp belongs to the immutable source revision, not each
subsequent polling attempt. The application must retain that capture record.

Point selection uses the latest eligible observation date and then latest
available revision; numeric revision ordering is used only when explicitly
validated. Opaque same-time conflicting versions are SOURCE_ERROR. No fallback
to a convenient older value hides an eligible source error. All warmup points
use versions knowable at the current decision cutoff. Later revisions can
change later snapshots while immutable-prefix replay preserves earlier ones.

`LATEST_VINTAGE_DESCRIPTIVE_ONLY` points cannot enter recorded-as-available
snapshots. A separately requested descriptive build keeps its tag throughout
measurements and report coverage and cannot pass live/prospective confirmation.

## Measurements and state

The exact 18-sensor registry is pinned by the 6B-2G canonical digest and a
validated immutable runtime projection. A mutated registry cannot retain the
same identity while altering freshness, membership, method or required inputs.

All implemented active formulas follow the frozen definitions: log return20,
relative log return20, sample RV20, RV5/RV20, VIX level and implied/realized gap,
HY OAS, 2Y/10Y/slope, SOFR/EFFR spread, and the nine-sector relative vector.
Twenty-return windows require 21 consecutive calendar sessions; a missing bar
is not compressed or filled. Insufficient warmup, stale data, source errors and
zero variance denominators remain distinct null-valued outcomes. Logs are
computed by differences to avoid overflow in a direct price ratio.

True breadth, top-seven weight and Mega-7 contribution stay visibly blocked.
RSP/SPY remains `PROXY_ONLY`, with `TRUE_BREADTH_UNAVAILABLE` and concentration
coverage disclosed. SPY rising alongside RSP falling remains separate evidence;
no synthetic global regime is inferred.

The complete sector vector requires all nine members. Valid individual sector
members survive as explicitly partial context when one fails; they are not a
complete vector, ranking or nine independent confirmations. `StateBuild` carries
this detail alongside, not inside, the registered dimension-measurement list.
Member records are typed one-element sector vectors with explicit member/partial
qualifiers, sorted by canonical subject identity when bound.

Snapshot availability describes active-required measurements (13). Coverage
separately counts all registered (18), optional (2) and blocked (3) measurements.
Thus all required measurements can be AVAILABLE while total coverage remains
PARTIAL because true internals are blocked. The report says DEGRADED coverage;
it does not call missing internals normal.

Every content identity pins effective input/revision IDs, descriptor/binding
versions, method/configuration, cutoff, calendar and protocol. Set-like lists
are canonicalized. `StateBuild` retains exactly referenced points, validates
lineage/cutoffs/methods and carries resolvable evidence. Shared SPY source
observations have shared lineage across return/RV/relative measurements.

## Report projection and exclusions

`project_market_now` implements the MarketNow v0.2 state projection, not the full
SentinelReport/priority/discovery/portfolio builder. Component entries preserve
StateValue as-of/status/source/evidence/method/qualifiers; an available typed
value includes units and scalar amount or sector members. Unavailable is null.
Partial sector context stays explicit; lagged economic levels keep their actual
observation timestamp. Optional snapshot references pin exact schema/protocol.

`reference_values`, `conditional_forecasts` and `source_event_ids` are empty.
There is no S/D calculation, new detector, forecast, Priority predicate, trade
or autonomous action. Activity Anomaly behavior and the archived EWMAC decision
are unchanged. Composite research belongs to 6B-2I, changes to 6B-2J and forecasts
to 6B-2K. The parent 6B-2 production-detector task remains open.

## Verification and operational gate

Focused tests cover independent numerical expectations, contradictory basket
states, complete/partial sectors, stale/missing/PIT/zero-variance cases,
publication/capture cutoffs, revision ambiguity and later corrections, source
and unit mismatch, window/date alignment, source holidays, offsets/DST/early
closes, immutable inputs and replay/lineage identity.

The standalone conformance runner freezes one synthetic input fixture, replays
25 completed decisions both as prefixes and with a full future-containing input
set, and compares every active scalar plus sector member to independent NumPy
calculations from known fixture returns. It writes content-pinned evidence and
MarketNow samples and explicitly distinguishes fixture coverage from live
coverage. See [verification artifacts](../../research/sentinel/6b-2h-conformance/README.md).

Live operational gate is **BLOCKED_DATA**: verified real source bindings and a
recorded live observation sample are not supplied by this fixture task. Its
95% required-feed coverage requirement remains untested, with unknown coverage,
not an invented pass from synthetic completeness. No market-effectiveness or
predictive-accuracy claim follows from conformance. Provider/vintage capture and
operational coverage must be verified before live promotion; this is independent
of the next mathematical reference research checkpoint.
