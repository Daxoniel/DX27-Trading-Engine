# 6B-2H implementation conformance

This archive records **synthetic fixture conformance**, not a real market run
or live-provider certification. It is separate from EWMAC's frozen research.
The unchanged [6B-2G protocol](../6b-2g-contracts/protocol.json) remains normative.

[Runtime architecture](../../../docs/architecture/sentinel-market-state-runtime.md)
describes the implemented state/availability/lineage and report projection.
The standalone runner compares independent known-return formulas and immutable
prefix/full-input replay over 25 synthetic decision sessions. It produces a
sample state evidence bundle and MarketNow projection, with explicitly blocked
true-breadth/concentration sensors and disabled references/detectors/forecasts.

```bash
PYTHONPATH=src .venv/bin/python runners/standalone/market_state_conformance.py \
  --output-dir work/task-6b-2h-conformance
.venv/bin/python -m pytest \
  tests/unit/test_sentinel_sensor_inputs.py \
  tests/unit/test_sentinel_market_state.py -q
```

Artifacts:

- [Conformance report](state_conformance_report.json): 25 decisions, 575 formula
  comparisons, maximum absolute error 1.5276668818842154e-13; zero causal,
  replay, imputation and proxy violations.
- [MarketNow sample](market_now_sample.json): explicitly synthetic, including
  contradictory SPY/RSP states and unavailable true internals.
- [Canonical state/evidence bundle](state_evidence_sample.json) and
  [fixture bindings](fixture_bindings.json): source/method/lineage identities.
- [Artifact hashes](artifact_hashes.json) and [verification](verification.md).

Two independent runs of the pinned implementation produced byte-identical
artifacts. The report pins the implementation commit before evidence was archived. Fixture bindings are
marked `fixture-only`; live operational status is BLOCKED_DATA, coverage unknown.
Provider metadata verification, real recorded availability/vintages and the
95% operational coverage gate remain necessary before live promotion.
