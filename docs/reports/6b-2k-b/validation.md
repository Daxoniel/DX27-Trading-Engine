# 6B-2K-B validation — 2026-10-12

## Software and browser

- Repository suite: 832 passed, one live-network test deselected.
- Final focused parsing, comparison, persistence, rendering and HTTP checks:
  137 passed after the direct S&P500/S&P493/Mega7 total-earnings addition.
- Desktop/mobile headless Chromium: the real page issued one refresh POST,
  loaded both source records and the brief/valuation section, displayed Berlin
  time and had no horizontal page overflow. The report iframe permits no scripts.
- Review fixes cover target-period switches, unavailable latest sources,
  atomic latest publication, concurrent writers/startup, source-store isolation,
  source/page identities, date precision and Windows launcher success checks.
- Separate Linux/Windows CI checks are provided for the new report path and the
  PowerShell launcher parser. Target-machine execution remains a user deployment
  check; Linux checks alone are not Windows operational acceptance.

## Private actual-source execution

The final run retrieved FactSet's official current PDF and four Yardeni charts.
FactSet returned 38 text-verifiable metrics and explicit partial coverage;
image-only or absent values remained unavailable. Yardeni returned 23 verified
legend metrics and seven content-addressed captures, including three separately
dated group total-earnings values. Existing market-source refreshes had no failed
feed in these two visits.

The first visit after adding the group chart had 58 comparable metrics and new
coverage; it correctly reported `INCOMPARABLE`, not a confirmed trend change.
The next actual refresh had 61 comparable metrics, no value changes and
`UNCHANGED`. Refresh elapsed times were approximately 28 and 39 seconds.
Completed visit archives survived a verification-server restart.

Real source payloads, extracted metrics, report JSON and browser screenshots are
retained only in ignored private work directories. No vendor payload or real
market-value fixture is published here. This execution verifies source wiring,
comparison semantics and operation, not trading or forecasting effectiveness.

## Delivery scope

The Windows launcher and [operation guide](../../operations/sentinel-research-report.md)
provide the local entry point. The original static HTML remains a saved artifact;
refresh-on-open requires the loopback page. Sentinel new-feature/research work is
frozen to maintenance of this delivered report. Existing pilot dates, records,
gates and production switches remain as recorded. Intraday automated quantitative
trading is the next separately scoped task.
