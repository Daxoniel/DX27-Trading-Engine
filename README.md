# DX27-Trading-Engine

Trading-system foundations with a local Sentinel market/research report.
Sentinel feature development is frozen; the next separately scoped direction
is intraday automated quantitative trading.

- [Run INTRA-1A intraday replay and transaction ledger](docs/operations/intraday-replay.md):
  synchronized ORB replay, minute inputs, modeled costs and account ledgers.
  Historical SIP/Q1 ledger acceptance passed; effectiveness remains unverified.
- [Opening RVOL selection](docs/architecture/intraday-opening-volume.md) and
  [P0–P3 intraday delivery gates](docs/architecture/intraday-delivery-roadmap.md).

- [Open the final Sentinel report on Windows](docs/operations/sentinel-research-report.md):
  FactSet/Yardeni refresh when the page opens, with a brief saved-visit comparison.
- [Historical Shadow Mode and restart recovery](docs/operations/intraday-recorded-shadow.md):
  reuse sealed old minute bars offline; no realtime subscription or broker orders.
- [Offline order lifecycle and restart reconciliation](docs/operations/intraday-order-lifecycle.md):
  partial fills, unknown outcomes and historical trace checks against a local simulator.
- [Current roadmap and freeze](TODO.md).
- [System architecture](docs/architecture/system-overview.md).

The report is read-only research context. It does not place trades or certify
predictive effectiveness.
