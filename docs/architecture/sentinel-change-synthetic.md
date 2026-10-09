# 6B-2J-B — Synthetic Implementation & Causal Conformance

The research implementation follows the merged 6B-2J-A lock without changing its
protocol bytes or thresholds. It is outside the production detector registry,
creates no DetectionResult, and makes no provider or live-pilot calls.

## Implementation

`change_inputs` creates the registered PCG64 scenarios and an arrival-ordered
synthetic close journal. Immutable original-cutoff snapshots store both constituent
capture IDs for each daily log return. The numerical firstSeen coordinate is a
synthetic decision-cutoff index, mapped to the pinned XNYS schedule; it is not
historical evidence from a market provider. A late revision is retained in the
journal and does not rebuild old primitive snapshots. Missing constituent closes
prevent return/spread calculation; delayed closes become usable only after arrival.

`change_detection` implements the frozen two-session threshold persistence and
two-sided CUSUM, fixed threshold and NO_CHANGE controls, and archived EWMAC 64/256
transitions. All comparisons share the 252-prior-session warmup requirement; the
archived EMA's intrinsic longer readiness is preserved and disclosed as abstention.
EWMAC applies to trend only. Volatility/relationship rows report NOT_APPLICABLE,
not a fabricated EWMAC statistic. Zero normalization variance causes abstention.

Threshold persistence rearms only on a valid nontrigger evaluation. CUSUM resets
both accumulators after every raw trigger, including suppressed ones. Cooldown
retains the first alarm, suppresses distances 1..5 and permits distance 6, shared
across directions. Missing inputs break continuity and require a fresh warmup.

`change_scoring` separately generates the frozen future surrogate labels and
chronologically matches alarms once. Future targets are never supplied to replay.
Scorable target sessions stay in the denominator during detector abstention. TP
alarms are attributed to alarm sessions, TP targets to anchor sessions; FP/FN and
availability have their own session sufficient statistics. All subjects/methods
use identical 40-session bootstrap draws, 1,000 replicates and seed 627. Matching
is never repeated at artificial block joins. Undefined precision/F1 is retained;
zero F1 is used only in paired comparison when a method has no alarms.

`change_synthetic` executes all 19 cases and both frozen 20-seed partitions.
`change_archive` verifies full output hashes, preserves every metric row, retains
two prespecified full-evidence seeds per case and exactly replays their streams.
Full omitted evidence shards are reproducible and their original hashes retained.
No metric or failed trial is filtered out. Descriptive cross-trial medians are not
pooled promotion scores. No real-development candidate selection or final freeze
is performed, and the prospective confirmation clock has not started.

## Observed result

760 trials yielded 38,000 metric rows: 15,200 candidate strata, 18,240 applicable
baseline strata and 4,560 non-applicable EWMAC strata. Candidate outcomes:
15,186 INSUFFICIENT_EVIDENCE, 14 FAIL, zero PASS. This result does not promote either
candidate, and it does not establish market effectiveness.

The 14 numeric failures occurred in heavy-tailed stationary volatility-decrease
strata with enough surrogate labels. Recall was below .60: persistence roughly
.17–.34, CUSUM roughly .03–.06. These are retrospective surrogate label matches;
stationary Student-t inputs have no injected structural shift. This demonstrates
both detector/target mismatch and the limits of treating statistical labels as
market ground truth. No parameters or labels were changed after these results.

A 1,200-session sequence cannot yield 30 trend targets after 252 warmup sessions
and 40-session followup/refractory rules: at most 23 total anchors, before dividing
by direction. Independent seeds cannot be joined to satisfy the frozen minimum.
Other scenarios also often have fewer than 30 targets or undefined metrics.
Insufficient evidence does not mean zero alarms or a successful detector.

All six registered causality violation counters were zero. Post-archive replay
checked 950 retained subject/method streams, including actual missing-history
eligibility and exact archived values. The original execution report is preserved alongside the canonical report, which
adds independently repeated prefix/gap and exact trace checks. All normalization
windows recognize exact constant samples as zero variance without an epsilon floor;
the synthetic initial close uses the same log-price seed calculation as its path,
preventing a roundoff pseudo-return in the zero-variance fixture.

## Evidence and reproduction

Artifacts reside in `research/sentinel/6b-2j-b-synthetic/`: canonical and original
reports, all per-case per-seed metrics, representative input/lineage/decision
columns, matching details, bootstrap intervals, explicit failures, session grid,
full execution hashes and descriptive summaries. The gzip header is deterministic.
Run at the repository root with recorded Python/NumPy/calendar versions:

```bash
python -m dx27.intelligence.sentinel.research.change_synthetic --output work/change-full
python -m dx27.intelligence.sentinel.research.change_archive --execution work/change-full --output work/change-archive
```

Destinations must not already exist. Full-run evidence shards are not committed to
keep the repository bounded; complete metric reporting and prespecified evidence
samples are committed. Numerical replay and retained evidence are verified against
current source. The canonical report includes additional archive-audit metadata and therefore
has its own hash, distinct from the original execution report.

## Gates and next work

Implementation/causality conformance PASS; synthetic efficacy has no passing
stratum. Real validation remains BLOCKED_DATA, production remains disabled and
participation labels remain blocked. 3A still needs its originally required native
acceptance evidence; this offline task neither operates nor certifies that host.

6B-2J-C cannot start real validation until the existing PIT data and S/D research
gates pass. Review the synthetic limitations before designing additional research;
any expanded event-count stress design or changed candidate/target needs a new
reviewed protocol version before results. Do not silently extend this sequence,
relax thresholds or implement production detectors to compensate for weak results.
