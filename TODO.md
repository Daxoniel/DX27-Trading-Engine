# DX27 Sentinel Roadmap

DX27's active development path is Sentinel-first. This roadmap distinguishes
working repository state from frozen architecture and future work:

- **IMPLEMENTED / COMPLETED** — present as working contracts or behavior with
  tests.
- **FROZEN DESIGN** — agreed architecture that is not yet implemented.
- **NEXT** — immediate implementation work.
- **DEFERRED** — intentionally outside the current implementation path.

## Implemented / completed

- [x] **6A-1 Common Foundation** — explicit data status, subjects, observation
  windows, provenance, canonical serialization/hashing, and stable identity.
- [x] **6A-2 Event Foundation** — deterministic `DetectedEvent` contracts and
  the frozen nine-category primitive vocabulary.
- [x] **6A-2 Correctness Hardening** — evidence/lineage membership validation,
  total canonical evidence/provenance ordering, and input-order-independent
  event identity.
- [x] **6A-3 Observation / Universe Foundation** — observation envelopes,
  coverage, universe membership and activation, discovery eligibility, and
  descriptive known-interest snapshots.
- [x] **6B-1 Daily Activity Anomaly Detector** — deterministic, no-lookahead,
  completed-daily-observation detection with explicit availability and
  insufficient-history outcomes.

## Current checkpoint

- [x] Architecture documentation sync after 6B-1.

## Next

- [ ] **6B-2 Trend Change + Volatility Change** — implement `TREND_CHANGE` and
  `VOLATILITY_CHANGE`. Formula, indicator, and threshold selection belongs to
  that research and implementation task; none is selected here.

## Planned

- [ ] **6B-3 Relative Strength + Relationship Detection**.
- [ ] **6C Blind Spot Discovery** — implement the frozen Discovery design.
- [ ] **6D Priority Engine** — implement the frozen deterministic, non-weighted
  priority design.
- [ ] **6E SentinelReport** — implement the frozen evidence/report contract.
- [ ] **6F GPT Analyst Layer** — add optional interpretation downstream of
  deterministic Sentinel evidence.

The Monitoring Universe, Blind Spot Discovery, Priority Engine, and
SentinelReport architecture is **FROZEN DESIGN**, not current implementation.
GPT Analyst is future and interpretive, not part of deterministic detection.

## Deferred

- [ ] Execution integration.
- [ ] Broker actions.
- [ ] Autonomous position sizing.
- [ ] Live autonomous trading.

Sentinel remains read-only. Existing historical replay, simulated execution,
ORB bot, and Yahoo/LEAN adapter work is retained as **LEGACY / EXISTING
CAPABILITY**; it is not the active Sentinel development frontier.
