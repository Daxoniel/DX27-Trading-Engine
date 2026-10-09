# 6B-2J-A — Change Detection Protocol Pre-registration

This task freezes research design. It does not implement detectors, run synthetic
experiments, start prospective confirmation or enable production. The existing G
protocol remains byte-identical and supplies targets, baselines, splits, matching,
bootstrap and promotion gates. Machine-readable definitions and hashes reside in
`research/sentinel/6b-2j-a-change-protocol/`.

## Questions and subjects

Detect sustained trend reversals for SPY and RSP separately, SPY volatility
changes, and RSP/SPY and QQQ/SPY daily-spread changes. SPY is one sensor: results
must be reported per subject/family/direction. Divergent subjects are legitimate
observations, not forced into a single market label. Participation remains blocked
without admitted constituent PIT data and its own target version. No forecast or
probability of future market returns is emitted.

VIX, HY OAS and yields provide context with availability and quality; they do not
vote in the v1 detector. S/D remain unvalidated reference context. Their presence
cannot turn invalid primitive evidence into a detection or change admission.

## Small fixed candidate set

Compare a two-session persistence filter on the existing causal thresholds and a
two-sided CUSUM with fixed k=.5/h=5. CUSUM uses current primitive innovations
normalized by the preceding 252 eligible sessions: log returns, log absolute
returns, or constituent daily return spreads. Its recursion is documented by
[NIST](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/cusum.htm),
reference ID `REF-JA-NIST-CUSUM`. The rolling normalization, volatility surrogate
and financial acceptance policy are our research choices. Statistical process
control documentation does not demonstrate market efficacy.

The frozen no-change, causal threshold and archived EWMAC 64/256 comparators
remain unchanged. EWMAC is research evidence, not an approved production model.
There is no parameter tournament or post-audit threshold tuning in this version.
A candidate that cannot beat the frozen baseline is allowed to fail.

CUSUM increase/decrease is a distributional-change direction; for trend it is
mapped to positive/negative direction, then evaluated against the already frozen
sign-reversal target. A drift that does not reverse sign may be a false alarm under
that target. This mismatch is disclosed rather than fixed after inspecting results.

## Causality and abstention

Inputs must be available at the original cutoff. A missing constituent, stale
value, zero normalization variance, invalid absolute-return logarithm or
incomplete warmup produces ABSTAIN. Gaps reset candidate accumulators and crossing
continuity. No interpolation, retrospective change-date credit or rewriting
original-cutoff snapshots. Five-session cooldown preserves raw suppressed alarms.
Detailed edge and reset rules reside in protocol.json; they must be implemented
before execution without result-driven choices.

## Evaluation and stage gates

The inherited surrogate labels use future outcomes only for offline evaluation;
the online candidate never reads them. Followups, greedy label spacing and [0,5]
one-to-one matching remain unchanged. Abstentions retain missed-target exposure.
Per-stratum requirements remain 30 targets, precision/recall .60, median delay <=3,
p90 <=5, unmatched rate <=12/252, availability .95 and F1 uplift .05 with a strictly
positive paired block-interval lower bound. Zero denominators are insufficient.

6B-2J-B implements sequential replay and the registered synthetic cases: stationary
and heavy-tailed controls, opposite trend shifts, volatility scaling, constituent
spread shifts, transients, ramps, joint changes, missing/delayed data, corrections
and zero variance. Separate development/acceptance seeds are frozen now. Known
injected boundaries are diagnostic, not replacements for independent frozen
labels. Integrity must pass exactly; effectiveness may FAIL or remain insufficient.
Synthetic performance cannot establish real market effectiveness.

6B-2J-C real development work remains blocked by admitted PIT data and existing
S/D research gates. Previously observed 2005–2026 history is not fresh holdout.
Final candidate freeze comes after eligible development selection. 6B-2J-D starts
confirmation only at the next full XNYS session after that final commit, with at
least 252 sessions plus completed label followup. This design commit does not
start that clock. Forecast research remains a separate 6B-2K gate.

## Parallel operation

Track A continues the fixed October 8–November 4 coverage pilot and subsequent
126/252-session history. User-reported Windows reboot recovery and actual mail
receipt are archived in `deployment_acceptance.json`; process observations and
hash-preserving single-writer handoff are recorded separately. October 8's four
MISSED slots remain unchanged. PASS_USER_REPORTED_ACCEPTANCE for infrastructure
does not imply source coverage PASS or data admission.

Track B can prepare and test synthetic implementations now. No additional live
collector is launched and no runtime health file is rewritten to certify research.
