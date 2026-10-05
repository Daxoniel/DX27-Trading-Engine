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
- high-relevance Contextual assets
- default intraday interval: 15 minutes

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
