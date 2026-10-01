# DX27 Roadmap

DX27 is a modular trading decision system.

Trading logic must remain independent from infrastructure such as LEAN,
market-data providers, broker APIs, and backtesting engines.


# v0.1 — Architecture Foundation

Goal:

Establish stable system boundaries before developing production strategies.

## Repository Architecture

- [x] Create Python-first repository
- [x] Create Core models
- [x] Validate unit-test workflow
- [x] Validate historical market-data access
- [x] Validate DX27 → LEAN signal integration
- [x] Validate end-to-end prototype backtest
- [x] Split code into Intraday / Investment / Strategic domains

## Core Contracts

- [ ] Define MarketDataPort
- [ ] Define ExecutionPort
- [ ] Define PortfolioPort
- [ ] Define IntradayBot contract
- [ ] Define TradeIntent
- [ ] Define StrategyMetadata
- [ ] Define adapter contract tests

## Architecture Rules

- [ ] DX27 Core never imports LEAN
- [ ] Domain logic never imports broker SDKs
- [ ] Runners contain no trading logic
- [ ] Backtest / Paper / Live share the same strategy logic


# v0.2 — Intraday Strategy Platform

Goal:

Create a replaceable and testable short-term trading framework.

## Baseline Strategy

- [ ] Select one mature open-source technical strategy
- [ ] Wrap it through the IntradayBot contract
- [ ] Support native DX27 intraday bots
- [ ] Support external strategy adapters
- [ ] Standardize BotSignal
- [ ] Standardize TradeIntent

## Technical Services

- [ ] Technical feature service
- [ ] Technical rule-pack interface
- [ ] Strategy configuration
- [ ] Strategy version metadata
- [ ] Strategy registry

## Backtesting

- [ ] Build reusable backtest harness
- [ ] Historical-data adapter
- [ ] Record standardized performance metrics
- [ ] Multi-symbol testing
- [ ] Strategy version comparison
- [ ] Regression testing


# v0.3 — DX27 Intraday Strategy Iteration

Goal:

Iteratively add DX27-specific technical knowledge.

- [ ] Technical Rule Pack v1
- [ ] Trend filters
- [ ] Momentum filters
- [ ] Volume filters
- [ ] Volatility filters
- [ ] VWAP research
- [ ] Breakout research
- [ ] Mean-reversion research
- [ ] Compare every version against baseline

## Runtime

- [ ] Paper-trading adapter
- [ ] Paper-trading validation
- [ ] Execution logging
- [ ] Decision explanations
- [ ] Strategy health monitoring


# v0.4 — Investment Domain

Goal:

Implement the DX27 27-rule framework for medium- and long-term investment
decisions.

## DX27 Core 27

### 18 Veto / Risk Rules

- [ ] Define rule schema
- [ ] Implement 18 veto rules
- [ ] Add evidence and explanation output

### 9 Positive Triggers

- [ ] Define trigger schema
- [ ] Implement 9 positive triggers
- [ ] Add evidence and explanation output

## Investment Analysis

- [ ] Technical context
- [ ] Fundamental context
- [ ] Rule evaluation
- [ ] Triggered veto rules
- [ ] Satisfied positive triggers
- [ ] Structured advisory output
- [ ] `dx27 analyze TICKER`


# v0.5 — Strategic Domain

Goal:

Support major portfolio allocation and annual rebalance decisions.

- [ ] Capital Doctrine v1
- [ ] Portfolio context
- [ ] Macro context
- [ ] Sector context
- [ ] DX27 Core 27 integration
- [ ] Doctrine + Core 27 evaluation
- [ ] Annual rebalance engine
- [ ] Strategic allocation output


# v0.6 — Multi-Bot Coordination

Goal:

Coordinate multiple strategies without coupling them together.

- [ ] Coverage / Discovery service
- [ ] Dynamic candidate universe
- [ ] Bot activation
- [ ] Strategy Coordinator
- [ ] Signal conflict handling
- [ ] Risk coordination
- [ ] Capital allocation across bots


# v1.0 — Portable DX27 Platform

- [ ] Multiple Intraday Bots
- [ ] Investment Advisory
- [ ] Strategic Rebalance
- [ ] Historical Backtesting
- [ ] Paper Trading
- [ ] Multiple infrastructure adapters
- [ ] LEAN adapter
- [ ] Alternative engine adapter
- [ ] Simple clone-and-run setup
- [ ] Contributor documentationke