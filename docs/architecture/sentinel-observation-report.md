# 6B-2H-1 — Readable Market Observation Report

This delivers a one-shot, descriptive report from the existing 6B-2H measurements.
It does not select a new model or certify forecasting/alert effectiveness. The
original protocols, pilot dates, source-admission gates and production switches
remain unchanged.

The report shows cap-weighted/equal-weight/technology/small-cap basket performance,
relative performance, realized/implied volatility, credit, rates and nine existing
sector proxies. It compares each rolling measurement with the preceding completed
session, lists missing coverage and retains source/capture identities. No new risk
threshold, composite score, prediction, Priority or Discovery engine is added.

## Time and comparison semantics

The existing capture/normalization path is reused. Every source row retains its
actual response-completion `first_seen_at`; unknown publication times stay unknown.
Current historical data is explicitly `LATEST_VINTAGE_DESCRIPTIVE_ONLY`.

A separately identified `DescriptiveSession` evaluates each completed observation
date at the same actual report watermark. Its canonical type, calendar source
version and exact watermark change identity. The frozen `TradingSession` and its
close+120-minute pilot cutoff are not edited or replaced in the pilot path. Future
captures and incomplete observation periods remain excluded.

Both current and preceding observations are recalculated from the **same latest
capture vintage**. These are not yesterday's issued report or historical-as-known
results. This permits current descriptive use of a freshly obtained history without
backdating captures. Twenty-return measurements require 21 consecutive closes;
comparing two adjacent 20-return windows requires 22. S/D's separate 126/252-day
original-cutoff support is neither bypassed nor required for these descriptive facts.

Observation labels are derived from the validated source's label policy. They are
separate from period-end timestamps and retrieval times. Full-day scalar windows
ending at midnight retain the preceding source date. If credit/rates repeat the
same available observation, the report says there is no new observation; it does
not assert that the market or credit condition was unchanged.

## Latest-attempt failure handling

The latest eligible attempt of each feed is evaluated at the actual report
watermark. A failed request, invalid completed data, empty usable history or
failed latest units-metadata validation removes that feed's earlier points from
both compared observations and their dependent measurements. Coverage falls and
the headline, badge and summary explicitly show incomplete collection. A later
successful attempt restores measurements; attempts after the watermark cannot
change a past-as-of report.

Raw captures remain sealed locally. Evidence shows the latest attempt and last
successful capture separately; prior metadata may establish a last-success record
for evidence only, and cannot restore failed current values.

## Scope limits

RSP is an equal-weight S&P 500 proxy, QQQ a Nasdaq 100 basket, and IWM a Russell
2000 basket. None is an exact Mega7/rest-of-S&P split. Constituent breadth,
concentration and Mega7 contribution stay explicitly unavailable. The nine sector
proxies do not constitute the full modern 11-sector universe. Lagged/stale/error
inputs remain visible; an available data response does not certify publication
clocks, operating coverage, statistical utility or real-data admission.

## Run

Use a dedicated, initially empty store, independent of the Windows pilot:

```bash
python -m dx27.adapters.sentinel.observation_runner \
  --store work/market-observation-captures \
  --output work/market-observation-output
```

Open `市场观察.html` directly in a browser. Markdown and a JSON evidence report
are emitted alongside it; the page has no scripts, CDN assets or model/API fees.
`--replay-only` reuses the dedicated captures without provider calls. Each output
directory must be new. Nonempty unmarked stores and pilot/configuration stores
are refused. No scheduler is started, no alert is sent and no pilot journal is
updated. Provider access is still necessary for a fresh local report.

## Verification and stopping point

Tests use independent price ratios and explicit source dates to verify the actual
watermark, same-vintage comparison, future-data isolation, incomplete bars,
missing/error propagation and pilot-store refusal. Renderer checks protect units,
escaping, cross-date derived values and partial sector context. The first real
capture is separately checked against raw provider rows.

The deliverable is one usable observation report and its reproducible entry point.
If it does not make market differences easier to understand than manually reading
the underlying charts, no further model or research expansion follows automatically.

### Private factual audit, 2026-10-09

The isolated run retrieved 24 Yahoo/Cboe/FRED responses on 2026-10-10, all
HTTP 200. Direct recalculation from locally retained provider rows matched 25
numerical values and 25 observation labels. The initial suite passed 603 tests
with one network test deselected. These checks establish arithmetic, timing and
content rather than prospective usefulness or research admission. Review fixes
and final validation are recorded separately.

## Publication boundary

Public endpoint access is not a redistribution license. This project has not
established permission to publish Yahoo, Cboe or ICE/FRED payloads or real market
values. The public package uses clearly labeled synthetic observations; real
reports and sealed captures are generated and retained locally for internal use.
The repository's license does not grant rights over third-party source data.

See [Yahoo's exchange/data-provider notice](https://au.help.yahoo.com/kb/finance-for-web/exchanges-cover-sln2310.html),
[Cboe website terms](https://www.cboe.com/terms) and
[ICE HY OAS series notes on FRED](https://fred.stlouisfed.org/series/BAMLH0A0HYM2).
These explain the publication restriction; this document does not adjudicate
individual fair-use exceptions or claim that all derived calculations require
permission. Other provider terms must be checked before public distribution.

The [publication repair record](../reports/6b-2h-1/publication-remediation.md)
identifies the withdrawn package and the limits of GitHub history cleanup.

## Public synthetic examples

Run the offline example generator from the repository root:

```bash
python -m runners.standalone.sentinel_observation_example \
  --output-directory work/new-synthetic-example
```

The generator accepts no real report input and makes no source requests. Its
fixed formulas create both an available example and a newer-SPY-503 example
through the normal measurement/report path. The ZIP contains only seven
allowlisted synthetic display/JSON/README files; no capture store or payloads
are copied. Repeated generation produces identical archive bytes.

Read the [synthetic display](../reports/6b-2h-1/market-observation.md) or download
[the public example package](../reports/6b-2h-1/synthetic-observation-demo.zip).
Real-report arithmetic is checked against private captures; the public record
exposes only source pages/hashes and aggregate verification information.

## Review-fix acceptance

The final revised suite passed **620 tests**, with one network test deselected.
The 38 report-specific checks include newer failures, HTTP-200 bad/empty data,
failed units metadata, recovery, past-as-of isolation, renderer disclosure and
offline synthetic-only packaging. The private original-capture calculation still
matches 25 values and 25 observation labels.

[Actual browser acceptance](../reports/6b-2h-1/visual-acceptance.md) covers normal,
degraded and local real displays. Only synthetic screenshots are public. Public
ZIP hashes and hash-only source provenance are listed beside the example. Frozen
research files and existing production/pilot implementations remain unchanged.

The old current-branch archive link returns 404, but the withdrawn commit-pinned
link still returns 200. Hosted-object erasure is PENDING_GITHUB_SUPPORT; the PR
remains on hold despite passing implementation and display checks.
