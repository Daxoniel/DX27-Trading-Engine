# 6B-2K-B — Public Research Report Refresh & Sentinel Freeze

The final Sentinel deliverable supplements existing price/volatility/credit/rate
observations with FactSet Earnings Insight and Yardeni Research. Opening the
local page checks the sources and displays a short research brief relative to
the actual previous saved visit. Sentinel then enters maintenance-only scope.
The next separately scoped direction is intraday automated quantitative trading.

## Inputs and interpretation

FactSet's official latest-report redirect supplies the current Earnings Insight
PDF. Text extraction retains the publication date, individual target quarters
or calendar years, printed revision baseline, and metric page. It reads the
aggregate forecasts/valuation and the sector revisions, price changes and EPS
revision counts present in prose. Image-only chart values remain missing rather
than inferred. Publication dates after the retrieval watermark are rejected.

Yardeni's current official pages identify four charts: Mega7 market-cap,
forward-earnings and forward-revenue shares; sector net earnings revisions
indices; S&P 500 fixed-calendar and rolling forward EPS; S&P500/S&P493/Mega7
forward total earnings. Group total earnings use billion dollars and retain
each group's own legend date; differently dated group values are not combined
into a concentration share. Cross-platform RapidOCR
reads only printed legends, not plotted series. Numeric values, dates, label
identity, confidence, range and duplicates are checked. Unknown publication
dates remain unknown; a legend with a month-only date remains month precision.
The local captures retain the original chart and OCR confidence for inspection.

The report pairs sector price and earnings revisions only where source,
forecast period, printed baseline and observation date agree. It distinguishes:

- Changes to the same quarter's estimated dollar earnings from earnings growth
  relative to the prior year.
- Fixed-calendar EPS consensus from rolling forward EPS, whose weights can
  change without an analyst upgrading either calendar year.
- NERI's three-month average of net estimate revision counts from dollar-level
  revisions and the fraction of companies with an upward EPS revision.
- Mega7 market-cap/earnings/revenue shares from true constituent breadth and
  contribution to the index's return.
- FactSet sector-index changes from the existing ETF 20-session observations.

The short explanations report support or disagreement between like-period
price and earnings observations. They are descriptive research context, not
validated turn warnings, numerical future probabilities or trading signals.
FactSet and Yardeni remain independent sources; they are not spliced into a
single estimate-revision history. Aggregate future growth remains visibly tied
to its forecast period. Earnings-season growth can mix actual results with
unreported companies' estimates.

## Refresh and snapshots

`observation_web` binds only to loopback. A page load immediately shows progress,
optionally displays the clearly labeled previous report, and makes one
same-origin POST to refresh. It checks research and existing market sources in
parallel. A new completed visit stores the full report before publishing the
latest pointer. Browser/server response caching is disabled.

Comparisons use the saved research metrics from the last actual visit, not a
newly recomputed past observation. Keys include provider, metric, subject,
target period, unit, baseline and estimate/final status. Retrieval timestamps,
HTML/PDF byte changes and content hashes alone do not imply a trend change.
Indicators of quarterly/NERI revision direction distinguish a sign change from
an update of magnitude; no statistical significance or detector validity is
claimed. Quarter switches, changed coverage and otherwise incomparable inputs
receive `INCOMPARABLE`, not `CHANGED`.

A first visit explicitly has no previous comparison. The report's unchanged
message applies only to obtained, comparable metrics; unchanged research does
not prove the market was unchanged. A failed latest source produces no current
metrics from that source. Other valid sources stay visible. Complete research
failure prevents a current trend conclusion, while a price-refresh failure
has its own visible warning. Old successful visits remain archived, with no
backfill into the current display. If a refresh fails before publication, the
previous saved report remains clearly labeled as old.

The data directory is independent of the Windows pilot and is marked for this
purpose. Pilot markers, unmarked stores and child-store redirection are rejected
before capture. OS file locks prevent concurrent process writers and are
released after exit/crash; atomic writes preserve completed snapshots and the
latest pointer. Existing files persist across browser closure and restart.

## Surface and references

The first section is **本次趋势简报**, with at most three main explanations and
three highlighted updates. Detailed sector comparison, earnings/structure and
source records are expandable. Existing market facts follow. Where an optional
old experimental forecast attachment exists, it moves to the final collapsed
appendix; the live entry point does not run that model.

FactSet editions use `REF-FACTSET-EI-YYYYMMDD`. Yardeni chart captures use
`REF-YARDENI-<CHART-ID>-<CONTENT-HASH-PREFIX>`, with exact hashes and original URLs
retained separately. The [source reference catalog](../../research/sentinel/references/market_research_v1.json)
describes verification scope. These are report references, not additions to the
frozen 18-sensor registry or a claim of admitted historical data.

Source payloads, extracted real values, visit JSON/Markdown and real screenshots
remain local and outside Git. Public source links/metadata, code and synthetic
tests may be reviewed. Public display of downloaded third-party reports or
charts is not enabled by this loopback implementation.

## Freeze

Delivered report operation and necessary correctness/security/source-format
repairs are the maintenance scope. Sentinel detector research, additional
models, scoring systems, Discovery/Priority engines and prospective experiments
are deferred. Existing pilot data and its operation are preserved, with no
automatic stop or reset. All original gates and production flags remain as
recorded. This task neither implements nor schedules the next intraday work.

See [Windows operation](../operations/sentinel-research-report.md) for setup,
restart, storage and failure handling.
