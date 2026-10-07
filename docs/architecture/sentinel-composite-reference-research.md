# 6B-2I Composite Reference & Relationship Research

This checkpoint implements research references and reproducible offline checks.
Real source admission and incremental effectiveness remain **BLOCKED_DATA**.
Implementation correctness does not enable operational reference attachments,
change detectors, forecasts, or composite Priority.

## Source admission and reference library

[Admission report](../../research/sentinel/6b-2i-reference/source_admission_report.json)
records actual read-only online captures: 25 Yahoo daily observations each for
SPY/RSP/QQQ/IWM and 9,288 Cboe VIX rows, through 2026-10-06. Payload hashes and
first-seen timestamps are archived; raw downloaded series stay outside Git.
Repeat connectivity checks with a new local capture directory:

```sh
.venv/bin/python runners/standalone/reference_source_probe.py --start 2026-09-01 --end 2026-10-07 --output-dir work/new-source-capture
```

This probe refuses to overwrite an existing capture. It is not a scheduled daily
collector or a validated scalar-feed adapter.

These downloads establish connectivity, not historical cutoff availability or
approved feed bindings. Operational original-cutoff coverage is unknown, not 100%.

FRED's [HY OAS notes](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
state that since April 2026 only three years of observations remain. This cannot
supply the frozen 2005–2026 development range alone. The captured metadata shows
an observation dated October 5 updated October 6; it motivates investigating
publication latency, but does not prove every historical release had the same lag.
HY context may be AVAILABLE at source age 1 while S requires source age 0.
No shift, fill, reweight, shorter-period substitution, or historical backdating
was introduced to manufacture coverage. The attempted FRED graph request was
HTML, not an admitted series download. Intraday source/vintage evidence remains
unverified for all real bindings.

[Reference library](../../research/sentinel/references/README.md) assigns stable
`REF-*` IDs to official source definitions, research motivation, statistics, and
local engineering choices. The versioned mapping covers all 19 feeds and 18
sensor contracts, pinned to the G protocol digest. It preserves the original
frozen G bytes and H descriptor shape. `references_for_sensor` joins a runtime
descriptor/version to the library and mapping digests, producing a separate
research annotation. Each sample annotation can resolve all its references.

Source definitions establish meaning and units, not economic accuracy or model
validation. Sector directory coverage is explicitly not individual historical
fund verification. Blocked constituent contracts carry local design references
until real PIT membership/weights are admitted. Cboe methodology PDF full text
returned HTTP 403; verification is limited to search metadata and the independent
official daily-close page/file. The library states this limitation explicitly.

## Frozen reference implementation

`ReferenceBuilder` consumes immutable `StateBuild` evidence at original
close-plus-120-minute XNYS cutoffs. It rejects latest-vintage descriptive tapes,
wrong protocol/calendar, changed descriptor bindings, and conflicting recorded
snapshots. Future snapshots cannot change an earlier result.

For each input, S uses the prior 252 XNYS sessions excluding current, with at
least 126 usable original-cutoff, source-age-zero measurements. H's `LAGGED_INPUT`
flag is used for age checks because economic sources can have exclusive-end
calendar windows; deriving age from UTC endpoint dates would be incorrect.
Stale repeats are excluded and missing calendar days remain missing. Percentiles
use midranks. Equity weakness averages inverse SPY/RSP percentiles; volatility
averages RV20/VIX percentiles; credit uses HY OAS percentile. Each group receives
one third and S is their weighted total times 100. Missing support yields null
with coverage counts, without weight changes.

D is the maximum absolute robust z of RSP/SPY and QQQ/SPY relative 20-session
returns against each pair's causal historical median and `1.4826*MAD`. Zero MAD
is insufficient history. Signed components remain visible. D is unbounded,
not bearish by definition, not a probability, and not combined with S.
S is limited US equity pressure, not comprehensive market or financial stress.

CompositeReference v1 retains exactly the frozen fields, finite values only when
AVAILABLE, explicit terms/support/qualifiers, deterministic IDs, and input
measurement IDs including historical support. Delta requires the immediately
previous XNYS snapshot and the same configuration; it cannot skip a missing day.
One additional historical snapshot is retained to recompute the prior reference's
full 252-session window. No reference is attached to operational MarketNow;
existing `reference_values` and `conditional_forecasts` remain empty.

## Conformance and interpretation

Run:

```sh
.venv/bin/python runners/standalone/reference_conformance.py --output-dir work/reference-conformance
```

The runner validates G and the bibliography/experiment locks, builds a synthetic
varying tape, compares S/D to independently calculated NumPy formulas, checks
full-history versus prefix results, and writes a sample plus hashes. Scenarios
include cap-weighted gains/equal-weight losses, quiet equity with high vol/credit,
a broad rally, and delayed HY publication. These are synthetic counterfactual
measurements, not claims about actual episodes or test-set performance.
Contribution and signed-pair explanations expose where each number came from.

Six single-group +/-20% weight perturbations, all five S member removals, and
both single-pair D ablations are descriptive sensitivity reports. Removing the
sole credit member leaves S unavailable. These research perturbations never
replace the frozen missing-weight policy or nominate a different winner.

## Frozen incremental-value experiment

[Experiment protocol](../../research/sentinel/6b-2i-reference/experiment_protocol.json)
and its hash lock specify four paired arms: vector, vector+S, vector+D,
vector+S+D. The primary comparison is vector+S+D minus vector; single-reference
arms are explanations, not alternate promotion candidates. Deterministic L2
logistic fitting uses development-only mean/population standard deviation,
zero-scale replacement by one, lambda 1, unpenalized intercept, no class weights
or hyperparameter search, and a specified gradient convergence tolerance.
No confirmation refitting or missing-input imputation is permitted.

`audit_recorded_tape` accepts typed causal state evidence and consecutive SPY
closes. It constructs fixed 20-session anchors, purges 40 sessions before the
2020 boundary, prevents target outcomes crossing split boundaries, and reports
missing features/outcomes. Future closes are used only for evaluation labels.
`compare_arms` fits development models and produces paired AUC/block-bootstrap
research statistics; it cannot issue prospective or operational PASS.
Bootstrap blocks are 40 calendar sessions, 1,000 draws, seed 627, with paired
score/outcome rows resampled through their original session blocks.

The previously observed history is development/audit. No empirical incremental
comparison was run because admitted original-cutoff tapes and long HY history
are unavailable. Numerical parameters are frozen before such results, but a
**final fitted candidate has not been frozen**. A source-admitted, fixed fitted
candidate and its commit must be registered before the first full prospective
session starts. The current implementation commit is not the confirmation start.

Confirmation still requires the frozen >=252 decisions with full follow-up,
>=30 positive and >=30 negative nonoverlapping outcomes, AUC improvement >=0.02
with positive 95% lower bound, and operational source coverage validation.
Accumulating these outcomes can require substantially more than one year.
No descriptive or synthetic result satisfies those gates. Prospective evidence
is INSUFFICIENT_EVIDENCE with zero sessions; real evaluation is BLOCKED_DATA.

## Completion boundary

Code/library/formula/scenario/experiment preparation is reviewable. Remaining
work is actual source/vintage admission, HY-history acquisition and age-zero
coverage measurement, registered fitted-candidate freeze, and prospective
collection/evaluation. If HY fails frozen S coverage, any delayed-reference
alternative must be explicitly versioned and preregistered separately. This
checkpoint does not silently modify S or move into 6B-2J/6B-2K.
