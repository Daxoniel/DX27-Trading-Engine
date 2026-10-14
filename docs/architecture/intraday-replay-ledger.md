# INTRA-1A — Intraday Replay & Transaction Ledger

Status: **IMPLEMENTED / HISTORICAL SIP AND LEDGER ACCEPTANCE PASSED** for
SPY/QQQ/IWM in 2025 Q1. See [the recorded evidence](../reports/intra-1a-real/validation.md).
Market effectiveness, realtime data and paper-account connectivity remain
**NOT VERIFIED**. The opt-in [INTRA-1B selector](intraday-opening-volume.md) is
separate from this unchanged baseline; no paper deployment or broker orders.

## Baseline and reuse

The baseline is `tanyuan_orb`: completed five-minute close beyond the current
09:30–10:00 New York opening range, ADX(14) >= 25, ATR(14) stop at 1 ATR and
profit trigger at 2 ATR. It is unleveraged and long only. Short signals are
logged and skipped; the original once-per-day signal policy remains, including
a skipped short consuming that day's signal. Each symbol has its own bot.

MarketContext, the existing bot, TargetToIntentPlanner, simulated account,
portfolio and execution interfaces are reused. The original single-symbol
HistoricalReplay remains. A synchronized runner handles simultaneous symbols.
Incremental Wilder features match the batch calculator on each prefix without
recomputing whole histories. Complete prior sessions can warm indicators;
no orders occur before `decision_start`.

## Data and clock

Input is aware, interval-start one-minute OHLCV CSV. Duplicate symbol/time keys,
nonfinite values, materially inconsistent OHLC, negative volume and naive times
are rejected. Relative 1e-12 floating boundary tolerance preserves input prices.

Alpaca requests historical `1Min`, `feed=sip`, `adjustment=raw`, ascending pages
and an end at least 15 minutes old. There is no IEX fallback. Completion metadata
records query bounds, symbols, retrieval times, CSV/archive hashes and original
response-byte hashes. The archive contains canonical JSON-lines response objects,
not byte-identical HTTP bodies. Both archive and CSV seals are checked on import.
Credentials are never saved. Existing outputs are refused.

Decision availability is **ASSUMED_AT_BAR_END_NOT_ORIGINAL_CUTOFF**. Retrieval
time is not original publication time. CSV without metadata is explicitly
LOCAL_CSV_UNVERIFIED. Declared download bounds retain whole missing sessions and
requested symbols. Only fully included sessions are traded. For local CSV with
no declared bounds, wholly absent leading/trailing dates cannot be discovered.

Initial real-data scope is SPY, QQQ and IWM. General stock studies need historical
membership, renames, corporate-action and borrow checks. The runner does not
certify these inputs or automatically adjust raw prices for splits/total returns.

The pinned XNYS calendar controls holidays, DST and early closes. Every scheduled
minute is processed, including absent rows. Outside-session/partial-request rows
are excluded and counted. At each open all available symbol opens are marked
before allocation; existing position exits precede entries. Simultaneous entries
use recorded lexicographic symbol order, not an alpha ranking.

Five-minute bars require all five observed minutes. The opening range requires
all six five-minute bars. Decisions use completed data; entries are eligible at
an open strictly after the decision, one minute later by default. Size uses ATR
and the last minute's volume known at decision time, never future fill-bar volume.
Missing execution bars reject entries.

Protective intraminute exits have BAR_INTERVAL timing with explicit bounds;
precise tick timing is not invented. Ambiguous stop/target touches select the
stop and are counted. Opening gaps have known precedence. Gap stops use the
worse open plus adverse friction. Profit exits are market-on-trigger, not
guaranteed limit fills. Entry cutoff is ten minutes before calendar close;
flatten is five minutes before it, including 12:55 New York on early-close days.
No fill is manufactured at the last available row.

## Costs, risk and accounting

Full spread, adverse slippage per side, per-share and minimum order commissions
are explicit. Each execution pays half the configured spread. Legacy execution
callers retain zero commissions unless they configure costs.

Defaults are simulation engineering assumptions, not broker quotations or fitted
strategy parameters: 0.25% planned trade risk, 1% aggregate open risk, 25% maximum
position notional, three positions, 1% daily equity-loss halt, and an entry cap
of 1% of the last minute's known volume. Integer shares must fit cash plus fees.
Planned stop risk includes modeled exit friction and both fees. Gaps can exceed
trade or daily loss budgets. The volume cap is a sizing proxy, not observed
available liquidity. Realized and marked exposure both affect the daily halt.

Changing spreads, regulatory/pass-through fees, impact, queues, partial fills,
rebates and broker margin are not simulated. Review costs against the actual
broker before effectiveness/deployment work.

Future missingness never suppresses earlier trades. A missing minute quarantines
its symbol for the current session and resets indicators. Zero-volume minutes
are quality failures, not verified liquidity. An unknown held interval makes the
trade path incomplete, halts account entries for that session, and exits at the
next observed open as data_gap_recovery. No unseen stop is reconstructed.

Incomplete sessions or unresolved holdings make aggregate net PnL and drawdown
null and performance_admissible=false. Modeled cash/marks/fills remain visible.
Complete synthetic runs also have performance_admissible=false. Complete
historical replay is calculability under recorded assumptions, not effectiveness
or original-cutoff approval. effectiveness=NOT_EVALUATED; production_enabled=false.

The ledger verifies cash against signed fill flows, equity against cash plus
holdings, trade net PnL against reference-price PnL minus every cost, and—when
flat—account change against completed trade PnL. Outputs retain config, source
seals, calendar identity, fills/trades, minute/daily equity, decisions and quality.

## Validation and references

Tests cover fees/affordability, synchronized risk allocation, accounting, prefix
invariance, gap stops, opening target precedence, intrabar ambiguity, missing
open/held/flatten/whole-session data, zero volume, early close, warmup and
incremental/batch parity. Mocked SIP pagination tests do not prove provider access.

- INTRA-REF-001: [ORB / stocks in play](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284).
  Future RVOL reference; this is not its five-minute strategy replication.
- INTRA-REF-002: [Alpaca data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).
- INTRA-REF-003: [Alpaca data plans](https://docs.alpaca.markets/us/docs/about-market-data-api).
- INTRA-REF-004: [Paper execution limits](https://docs.alpaca.markets/us/docs/paper-trading).
- INTRA-REF-005: [Intraday data checks](https://concretumgroup.com/how-to-detect-and-fix-problems-in-intraday-market-data/).

Next tasks: INTRA-1B RVOL selection on the same 30-minute interval; INTRA-1C fixed
paired historical comparison; INTRA-1D persistent paper execution/recovery.
