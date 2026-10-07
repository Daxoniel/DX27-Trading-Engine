# Sentinel Monitoring Universe v0.1

## Mission

Sentinel maintains a layered, role-based market-observation universe.

It must answer:

1. What is the overall market environment?
2. What is materially relevant to the user now?
3. What important behavior is emerging outside known holdings and watchlists?

## Universe tiers

- CORE
- CONTEXTUAL
- DISCOVERY
- EXCLUDED_NOISE

## Governing principle

Observe broadly; report selectively.

Monitoring eligibility does not imply reporting importance.

Economic roles are primary.
Specific tickers and proxies are replaceable implementations.

## Cadence

Primary mode:

- daily-first

Selective intraday monitoring:

- Core instruments
- current holdings
- Contextual assets explicitly activated for intraday monitoring
- default intraday interval: 15 minutes

Contextual activation is an observation-scope decision, not a P0/P1/P2
priority decision.

Discovery:

- daily only in v0.1

## Size budgets

Core:

- approximately 30–40 stable high-information instruments or series

Contextual:

- typically 25–75 active items
- hard maximum 100

Discovery:

- approximately 500 liquid US-listed assets
- daily evaluation only in v0.1

## Universe membership semantics

Core membership is stable and versioned.

Contextual membership must have an explicit activation reason and must not
grow permanently by default. Contextual activations should support expiry or
periodic reevaluation.

Discovery membership must be reproducible from explicit eligibility rules.
It must not depend on an arbitrary handwritten ticker list.

The same universe configuration and portfolio state should produce the same
universe membership.

## Discovery eligibility

Discovery Universe membership must require:

- adequate liquidity
- sufficient price/history coverage
- supported session semantics
- valid OHLCV observations
- stable instrument identity
- exclusion of penny stocks, microcaps, and economically redundant
  instruments by default

Exact quantitative thresholds are implementation-design decisions and are
not frozen in this document.

## Discovery purpose

Detect:

- unexpected leadership
- sector / industry rotation
- abnormal price behavior
- abnormal volume
- unusual relative strength
- synchronized behavior outside known areas of interest

Discovery is not a user watchlist.

## Data architecture

Reuse existing DX27 normalized boundaries where semantically appropriate:

- MarketDataPort
- MarketContext
- PortfolioPort
- PortfolioSnapshot
- HistoricalReplay

Sentinel must not introduce a parallel:

- market-data architecture
- account model
- portfolio model
- replay engine
- execution architecture

Historical evaluation must preserve completed-bar and immutable-prefix semantics.

## Sentinel architecture rules

S1 — Sentinel is read-only.

S2 — Sentinel findings are not BotSignals.

S3 — Sentinel reuses normalized DX27 state.

S4 — Sentinel detects broadly but reports selectively.

## v0.1 exclusions

Sentinel v0.1 does NOT include:

- direct provider access inside Sentinel
- order execution
- trading behavior
- BotSignal output
- automated portfolio modification
- strategy-health monitoring
- execution-health monitoring
- infrastructure telemetry
- news ingestion
- full global-equity coverage
- options-chain monitoring
- full futures monitoring
- automated actions of any kind

## Critical future data upgrades

Highest priority future authoritative inputs:

1. US 2-year Treasury yield
2. US 10-year Treasury yield
3. canonical VIX
4. market breadth
5. investment-grade / high-yield credit spreads
6. macro event calendar
7. corporate earnings / event calendar

ETF proxies may temporarily provide context but must never be mislabeled as the
underlying economic series.

## Data availability semantics

Missing data must never be treated as neutral market behavior.

Future Sentinel models should distinguish at least:

- AVAILABLE
- STALE
- INSUFFICIENT_HISTORY
- UNSUPPORTED_SESSION
- SOURCE_ERROR
- UNAVAILABLE

Detectors that depend on unavailable, stale, unsupported, or insufficient
inputs must not silently emit a normal market conclusion.

Data-health conditions are metadata, not ordinary market events.
Material coverage problems may later be aggregated by the reporting layer.

Missing data must never be interpreted as unchanged or normal market
behavior.

## Architecture placement

Sentinel belongs under:

```text
src/dx27/intelligence/sentinel/
```

It is a read-only Intelligence / Monitoring subsystem.

It is not:

- a trading domain
- a risk engine
- an approval engine
- an execution agent

## Status

DESIGN BASELINE FROZEN

Further changes require an explicit design revision.


## Multi-sensor design revision after 6B-2F

The [multi-sensor architecture](sentinel-multi-sensor-design.md) records the
agreed next direction, not implemented behavior or silently changed frozen
contracts. Task 6B-2G must explicitly freeze the sensor/availability and output
contracts, including any report schema revision. SPY remains one index sensor
and a portfolio benchmark; it does not alone establish market-wide conditions.
Composite references are optional evidence, not replacements for ordinal
Priority. Missing inputs remain explicit.


## Initial multi-sensor research subset — 6B-2G

The [frozen sensor registry](sentinel-sensor-contracts-v1.md) defines eight Core
and eleven optional Contextual feed roles for the first research subset. These
19 roles do not populate or replace the wider universe budget. Providers and
canonical subject identities require versioned bindings; registry inclusion
does not certify source availability. True constituent breadth and contribution
sensors remain blocked without validated PIT inputs. Existing tier/activation/TTL
and discovery eligibility semantics remain unchanged.
