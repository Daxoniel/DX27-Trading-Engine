# 6B-2I-1 HY OAS Source & Availability Audit

The source audit is completed; **HY source admission remains BLOCKED_DATA**.
No source binding, historical availability, pressure score, forecast, or market
effectiveness qualification is approved by this checkpoint.

## Verified public history

Actual FRED CSV retrieval requested 2005-01-01 through 2026-10-06. The export
contains 792 rows, 784 finite observations and eight missing values, from
2023-10-09 through 2026-10-05. This matches the official
[three-year history limitation](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
and does not meet the frozen development interval. Raw FRED percent converts to
basis points by multiplication by 100; missing values remain missing.

Three ALFRED export checks used nominal vintages 2026-03-31, 2026-10-05 and
2026-10-06, with the requested date verified against each CSV header. All begin
on 2023-10-09. The pre-April request did not restore earlier observations in
this captured route. This establishes the sampled exports' limitation, not that
all official archives or authorized ICE deliveries lack longer history.

## Date availability is distinct from cutoff availability

The fixed exploratory sample covers 16 completed XNYS sessions from 2026-09-15
through 2026-10-06. All exports were successfully retrieved and checked against
capture hashes. Fifteen have a latest observation on the nominal vintage date;
one has a one-session-old latest observation. The archive-date proxy therefore
shows 15/16 (93.75%) age zero and 16/16 age at most one.

**Those ratios are not operational coverage, nor a mathematical bound on actual
FRED or ICE cutoff availability.** The sample is small, and date labels are not
verified intraday publication/capture evidence. In particular, the October 5
nominal vintage includes the October 5 observation, whereas the FRED series page
was updated October 6 at 09:30 CDT. One possible explanation is source-release
date versus distributor-update date; the capture does not resolve that sequence.
These exports must not be assigned invented October 5 first-seen timestamps.

[ALFRED's official explanation](https://alfred.stlouisfed.org/help) distinguishes
source/provider release dates from FRED first-availability dates and notes that
archive additions can follow release. Its
[download interface](https://alfred.stlouisfed.org/series/downloaddata?seid=BAMLH0A0HYM2)
provides nominal vintage selection. Neither supplies the per-observation UTC
publication and actual capture timestamps required by the frozen replay contract.
Actual first-seen times in this audit are October 7, 2026.

Verified original-cutoff sessions are **zero**, and actual cutoff coverage is
**unknown/null**. The frozen >=95% operational gate is not evaluated from the
93.75% date proxy. Existing HY state context can permit age one; S still requires
age zero. This audit changes neither definition.

## Revisions and clock semantics

Across adjacent sampled exports, 11,655 overlapping finite values were compared
and no value changes were observed. This is a limited observation, not proof
that the series is immutable or a complete revision-history audit. Missing rows,
new observations, truncation and actual revisions remain distinct concepts.

ICE's [Bond Index Methodologies, April 30 2025](https://www.theice.com/publicdocs/data/Bond_Index_Methodologies.pdf)
identifies US high-yield valuation timing on page 72, including early-close
handling. Pages 6–7 allow delayed/suspended publication and case-by-case
restatement. A valuation clock is not an OAS delivery clock; a latest-value
export cannot reconstruct all original releases. Product-specific publication
and revision logs still require verification.

## Official acquisition candidate and concrete requirements

The [ICE Index Platform overview](https://indices.ice.com/registration?AccessType=Full)
describes historical index/statistic downloads and configured file delivery.
It is a candidate official acquisition route, not a verified delivery binding.
The public overview does not establish the exact HY OAS field, requested date
range, original vintages, timezone-aware publication logs, or existing account
entitlement. A real-time index-level product is not automatically the same as
the daily option-adjusted spread used by this contract.

[Acquisition requirements](../../research/sentinel/6b-2i-1-hy-oas-audit/acquisition_requirements.json)
prepare the exact requested evidence: product/field crosswalk, explicit units,
2005–2026 history with sufficient pre-2005 warmup, original and revised publication
timestamps, revision IDs, source calendar/label policy, delivery timestamps and
provenance. Account access and any cost remain unverified. No registration,
purchase, trial enrollment, external message, or request submission occurred.
The runtime context supplied no configured FRED/ICE credentials; no demo API key
or unverified third-party mirror was used.

## Reproducible audit and literature linkage

```sh
.venv/bin/python runners/standalone/hy_oas_source_probe.py --output-dir work/new-hy-capture
.venv/bin/python runners/standalone/hy_oas_source_audit.py --capture-dir work/new-hy-capture/captures --daily-dir work/new-hy-capture/daily-vintages --output-dir work/new-hy-audit
```

The probe has a fixed exploratory sample, refuses an existing capture directory,
and retains UTC first-seen/content hashes. It is not an installed daily collector.
The offline audit rejects HTML, wrong series/vintage headers, future observations
relative to nominal vintage, duplicate dates, nonfinite values, tampered payloads,
and timezone-naive captures. Failed/missing samples yield explicit unknown proxy
fractions; even 100% nominal-date completeness never approves actual cutoff
coverage. Raw licensed series and full source documents remain local, outside Git.

The [bibliography appendix](../../research/sentinel/references/hy_oas_audit_v1.json)
adds six stable official reference IDs linked to `hy_oas` / `hy_oas_level` and the
parent bibliography hash. The frozen I bibliography, sensor mapping, experiment
protocol/lock, G contracts, EWMAC archive and prior validation artifacts remain
unchanged. New audit manifests, aggregate report and hashes are archived in the
[research checkpoint](../../research/sentinel/6b-2i-1-hy-oas-audit/README.md).

## Next task

Proposed **6B-2I-2 — Recorded Availability Capture & Source Binding Validation**:
implement explicit daily capture and verify actual delivery units, labels,
publication/capture chronology, and revisions. HY long-history acquisition and
same-day delivery must be resolved before the full S experiment can pass source
admission. If an alternative delayed-credit reference is proposed, it needs a
separate version and preregistration; this audit does not choose that alternative.
6B-2J/6B-2K remain unopened.
