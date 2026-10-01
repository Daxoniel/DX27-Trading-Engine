# DX27 Roadmap

## v0.1 — Intraday Breakout MVP

Goal:
Build the smallest complete DX27 trading loop and validate it with backtesting.

### Core
- [x] Define `BotSignal`
- [x] Define `RuleResult`
- [x] Define base `Strategy`
- [x] Create first dummy strategy
- [x] Validate DX27 → LEAN communication
- [ ] Define `MarketContext`
- [ ] Define `FeatureSnapshot`
- [ ] Define market-data interface
- [ ] Define execution interface

### Intraday Breakout Bot
- [ ] Define trading universe
- [ ] Define timeframe
- [ ] Define trend filter
- [ ] Define breakout condition
- [ ] Define volume confirmation
- [ ] Define pullback / confirmation logic
- [ ] Define stop-loss logic
- [ ] Define take-profit logic
- [ ] Define trailing-stop logic
- [ ] Define end-of-day exit
- [ ] Define daily loss limit

### Backtesting
- [ ] Run single-symbol tests
- [ ] Run multi-symbol tests
- [ ] Test different market regimes
- [ ] Measure win rate
- [ ] Measure expectancy
- [ ] Measure max drawdown
- [ ] Measure profit factor
- [ ] Compare against simple baseline strategies

### Integration
- [ ] Implement LEAN market-data adapter
- [ ] Implement LEAN execution adapter
- [ ] Implement LEAN portfolio adapter
- [ ] Create LEAN runner
- [ ] Start paper trading


## v0.2 — Intraday Bot Pool

- [ ] Momentum Bot
- [ ] VWAP Reclaim Bot
- [ ] Mean Reversion Bot
- [ ] Strategy Coordinator
- [ ] Bot conflict resolution
- [ ] Capital allocation between bots


## v0.3 — Advisory Mode

Goal:
Allow manual analysis by ticker.

Example:

`dx27 analyze AMD`

- [ ] Manual ticker input
- [ ] Automatic feature collection
- [ ] Apply DX27 Core Rule Pack
- [ ] Run relevant bots
- [ ] Generate structured analysis
- [ ] Explain triggered veto rules
- [ ] Explain satisfied entry triggers
- [ ] Generate trading reference


## v0.4 — Coverage / Discovery

- [ ] Market scanner
- [ ] Dynamic watchlist
- [ ] Sector scanner
- [ ] Candidate ranking
- [ ] Automatically wake relevant bots


## v0.5 — Capital Doctrine

- [ ] Define market regimes
- [ ] Aggressive regime
- [ ] Neutral regime
- [ ] Defensive regime
- [ ] Capital allocation policy
- [ ] Long-term / short-term capital separation
- [ ] Annual rebalance support


## v1.0 — Multi-Strategy Decision System

- [ ] Intraday strategy pool
- [ ] Swing strategy pool
- [ ] Long-term strategy pool
- [ ] Advisory mode
- [ ] Autonomous mode
- [ ] Strategic rebalance mode
- [ ] Multiple infrastructure adapters
- [ ] Paper trading validated