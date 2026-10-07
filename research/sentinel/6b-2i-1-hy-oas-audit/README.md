# 6B-2I-1 HY OAS Source & Availability Audit

Source audit completed. **Admission: BLOCKED_DATA**. Actual original-cutoff
coverage remains unknown; no S, forecast or operational promotion.

See [the architecture audit](../../../docs/architecture/sentinel-hy-oas-source-audit.md)
for exact findings, source citations, limitations and the proposed next task.
The [bibliography appendix](../references/hy_oas_audit_v1.json) adds official
references without altering frozen bibliography or experiment locks.

Artifacts:

- `source_capture_manifest.json`: nine public source/export captures with hashes
  and actual UTC first-seen timestamps.
- `daily_vintage_capture_manifest.json`: sixteen fixed exploratory nominal-date
  ALFRED CSV captures; raw values remain local.
- `audit_report.json`: history limits, metadata/unit checks, date proxy and
  revision comparison counts; actual cutoff coverage explicitly null.
- `acquisition_requirements.json`: concrete official-delivery evidence request,
  prepared only, never sent.
- `verification.md`: offline parser/integrity/coverage safeguards and reproduction.
- `artifact_hashes.json`: hashes for this checkpoint and bibliography appendix.

The 15/16 age-zero date proxy does not evaluate the >=95% operational gate.
A source release date, distributor update date, valuation time, archive vintage
and actual capture time are separate facts. No historical timestamps are invented.
