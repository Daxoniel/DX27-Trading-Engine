# 6B-2I-1 Verification

Audit implementation commit: `360fa36` (source, CLI, tests and findings).

- Full offline suite: **522 passed, 1 network test deselected**.
- Focused audit suite: **8 passed**. Rejects wrong series/vintage identity, HTML,
  nominal-future observations, duplicate dates, NaN, tampered hashes and naive
  capture timestamps. Missing values remain null.
- A synthetic 100% nominal-date sample still has null original-cutoff coverage,
  zero verified cutoff sessions and BLOCKED_DATA admission. Missing one archive
  sample produces a null proxy fraction rather than silently shrinking denominator.
- Two independent offline runs on the same captured inputs produce byte-identical
  audit reports. Source payload hashes are verified before parsing.
- Nine actual public metadata/export captures and sixteen daily nominal-vintage
  captures succeeded. No public or private raw OAS series is committed to Git.
- FRED current export: 792 rows, 784 usable, eight missing, 2023-10-09 to 2026-10-05.
  All three sampled ALFRED vintages have the same earliest retained observation.
- Nominal-date sample: 15/16 age zero, 16/16 age <=1. Actual cutoff coverage is
  unknown. No proxy rate is compared as an operational coverage verdict.
- Adjacent sampled exports: 11,655 overlapping finite comparisons, no observed
  value revisions. This does not establish immutable history or complete vintages.
- Six new official reference IDs are unique and distinct from the eighteen parent
  entries; all parent links resolve and the parent bibliography SHA256 matches.
- Observed FRED metadata update date/time agrees with the documented date-versus-
  availability example. Valuation clocks are not reused as publication clocks.
- Frozen G protocol/lock, complete EWMAC archive, previous I artifacts, bibliography,
  sensor mapping and experiment lock remain byte-identical to the merged baseline.
  Legacy TODO preserved; local Markdown links, JSON, compile and diff checks pass.

Source audit completed; **source admission remains BLOCKED_DATA**. No final
fitted-candidate/prospective start, S activation, forecast, Priority or trading
behavior changes. Official acquisition requirements are prepared, not submitted.
