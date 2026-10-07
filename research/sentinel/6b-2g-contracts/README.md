# 6B-2G frozen multi-sensor contracts

This checkpoint freezes design and evaluation rules. It does not implement a
market-state runtime, certify providers, or establish market effectiveness.

- [Normative contract specification](../../../docs/architecture/sentinel-sensor-contracts-v1.md)
- [Machine-readable registry and protocol](protocol.json): 19 feed roles,
  18 measurement contracts (including three blocked PIT sensors).
- [Exact protocol lock](protocol_lock.json): raw-file and canonical hashes.
- [Offline validation report](validation/protocol_validation.json): design
  checks only; runtime/effectiveness flags are explicitly false.

Run from repository root:

```bash
PYTHONPATH=src .venv/bin/python runners/standalone/validate_sensor_protocol.py \
  --output-dir work/task-6b-2g-validation
.venv/bin/python -m pytest tests/unit/test_sensor_protocol.py -q
```

Changes to locked policy require an explicit new version/review and newly
locked evidence. Do not update this v1 protocol after observing prospective
results. 6B-2H is the next separate task. S/D, detectors and forecasts remain
gated under 6B-2I/J/K.
