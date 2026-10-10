# Verification — 6B-2J-B

- Full final regression: 582 passed, 1 network test deselected in 231.95s.
- Focused research tests: 34 passed in 5.03s, including independent capture-journal
  as-of queries, scalar sequential CUSUM, later window expiry, recent-window
  threshold and EMA revisions, and delayed-history visibility with original gap
  eligibility preserved; label/bootstrap/archive-corruption checks also pass.
- 760 frozen trials; all 38,000 metric rows archived and counted against report
  totals. Every registered case and both seed partitions executed.
- Revision visibility: all 40 seeds, 160 affected-subject oracle features with
  zero mismatches; 1,000 pre-arrival method/subject decision prefixes unchanged.
- Corrected SPY close 590 firstSeen 650 updates returns 590 and 591 and their
  constituent provenance at cutoff 650. Seed 62700 trend-SPY CUSUM score changes
  from -0.38172211342438683 to -0.3794294893471628, matching the independent
  cutoff oracle. Prior outputs remain fixed; no retrospective alarm or credit.
- 950 retained streams exactly replayed including historical-overlay provenance;
  six frozen integrity counters zero. Full output hashes verified before archive.
- Compared with the preceding execution, 6 revision-case and 80 delayed-case
  metric rows change; outcomes remain 15,186 INSUFFICIENT_EVIDENCE, 14 FAIL, zero PASS.
- All 95 existing research artifacts outside 2J-B unchanged vs preceding PR head;
  G/I/A protocols, sensor references and source-clock profile unchanged.
- Python 3.12.14, NumPy 2.5.3, pinned XNYS calendar recorded in report.
- Offline conformance PASS; market effectiveness NOT_TESTED. Real validation
  BLOCKED_DATA, production disabled; no candidate freeze or prospective start.
  Required native 3A acceptance remains separate and NOT_READY.

The initial complete-run attempt in this refreshed environment lacked the pinned
exchange-calendars dependency. After installing repository dependencies, the
complete synthetic run and regression above were executed anew; no partial run
is used as evidence. Frozen protocols, thresholds, labels, splits and pilot rules
were not modified. Live Windows tasks, raw provider stores and monitoring secrets
were untouched. Complete metric reporting, representative evidence, full hashes
and commands to regenerate omitted full-evidence shards are retained.
