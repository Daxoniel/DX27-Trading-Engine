"""Synchronized minute fills, completed five-minute ORB decisions and ledgers."""

from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from math import floor, isclose
from zoneinfo import ZoneInfo

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.intraday.data import IntradayDataset, aware_time, validate_bar
from dx27.adapters.simulated.account import SimulatedAccountAdapter
from dx27.adapters.simulated.execution import SimulatedExecutionAdapter
from dx27.adapters.simulated.portfolio import SimulatedPortfolioAdapter
from dx27.core.models.market_context import MarketContext
from dx27.core.models.portfolio_target import PortfolioTarget
from dx27.core.models.bot_signal import SignalDirection
from dx27.core.models.trade_intent import TradeSide
from dx27.domains.intraday.bots.intraday_breakout import IntradayBreakoutBot
from dx27.domains.intraday.features.streaming_breakout import StreamingBreakoutFeatures
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeSelector
from dx27.execution_planning.target_to_intent import TargetToIntentPlanner


MINUTE = timedelta(minutes=1)


@dataclass
class ReplayResult:
    summary: dict
    fills: list[dict]
    trades: list[dict]
    equity: list[dict]
    daily: list[dict]
    decisions: list[dict]
    quality: list[dict]
    selections: list[dict] = field(default_factory=list)


class IntradayLedgerReplay:
    """An unleveraged long-only baseline, with no future-day entry filters.

    Input bar times are starts. Decisions occur after five complete one-minute
    bars; a new order is eligible at an open strictly AFTER that decision.
    Standing protective exits use only subsequent bars. OHLC ambiguity selects
    the stop first and is counted; a missing held bar invalidates performance.
    """

    def __init__(self, config: IntradayReplayConfig | None = None):
        self.config = config or IntradayReplayConfig()
        self.account = SimulatedAccountAdapter(self.config.initial_cash)
        self.portfolio = SimulatedPortfolioAdapter()
        self.account.attach_portfolio(self.portfolio)
        self.execution = SimulatedExecutionAdapter(self.account, self.portfolio, costs=self.config.costs)
        self.planner = TargetToIntentPlanner()
        self.fills, self.trades, self.equity, self.daily, self.decisions = [], [], [], [], []
        self.issues = {}
        self.positions, self.pending = {}, {}
        self.bots, self.features, self.windows = {}, {}, {}
        self.used = False

    def _issue(self, session, symbol, code, at, count=1):
        key = (session.session_id, symbol, code)
        if key not in self.issues:
            self.issues[key] = dict(session=session.session_id, symbol=symbol, code=code,
                                    first_detected_at=at.isoformat(), count=0)
        self.issues[key]["count"] += count

    def _decision(self, symbol, at, action, reason, **extra):
        self.decisions.append(dict(symbol=symbol, decision_at=at.isoformat(), action=action,
                                   reason=reason, **extra))

    def _fill(self, symbol, quantity, side, reference, at, reason, decision_at=None, interval_end=None):
        self.execution.set_fill_context(at, {symbol: reference})
        before = self.account.get_account_snapshot()
        intent = self.planner.plan(PortfolioTarget(symbol, quantity if side == TradeSide.BUY else 0,
                                                  source_strategy="tanyuan_orb", reason=(reason,)),
                                   self.portfolio.get_portfolio_snapshot())
        if intent is None:
            return None
        report = self.execution.execute(intent)
        row = dict(fill_id=len(self.fills) + 1, symbol=symbol, side=side.value, timestamp=at.isoformat(),
                   decision_at=decision_at.isoformat() if decision_at else None, reason=reason,
                   requested_quantity=quantity, quantity=report.filled_quantity, status=report.status,
                   reference_price=report.reference_price, price=report.average_fill_price,
                   commission=report.commission, spread_cost=report.spread_cost, slippage_cost=report.slippage_cost,
                   equity_before=before.total_equity, cash_before=before.cash,
                   cash_delta=((-1 if side == TradeSide.BUY else 1) * report.filled_quantity * report.average_fill_price
                               - report.commission), cash_after=self.account.get_account_snapshot().cash,
                   interval_start=(at - MINUTE).isoformat() if interval_end else at.isoformat(),
                   interval_end=interval_end.isoformat() if interval_end else at.isoformat(),
                   time_precision="BAR_INTERVAL" if interval_end else "MODELED_OPEN")
        self.fills.append(row)
        return row

    def _exit(self, symbol, reference, at, reason, *, decision_at=None, interval_end=None):
        position = self.positions[symbol]
        fill = self._fill(symbol, position["quantity"], TradeSide.SELL, reference, at, reason,
                          decision_at, interval_end)
        if fill is None or fill["status"] != "filled":
            return
        entry, quantity = position["entry"], position["quantity"]
        commission = entry["commission"] + fill["commission"]
        spread, slippage = entry["spread_cost"] + fill["spread_cost"], entry["slippage_cost"] + fill["slippage_cost"]
        gross = (fill["reference_price"] - entry["reference_price"]) * quantity
        net = (fill["price"] - entry["price"]) * quantity - commission
        if not isclose(net, gross - commission - spread - slippage, abs_tol=1e-6):
            raise AssertionError("trade costs do not reconcile")
        self.trades.append(dict(symbol=symbol, quantity=quantity, entry_time=entry["timestamp"],
                                exit_time=fill["timestamp"], entry_fill_id=entry["fill_id"], exit_fill_id=fill["fill_id"],
                                entry_price=entry["price"], exit_price=fill["price"], gross_pnl=gross,
                                commission=commission, spread_cost=spread, slippage_cost=slippage, net_pnl=net,
                                planned_stop_risk=position["planned_risk"], exit_reason=reason,
                                path_complete=position["path_complete"]))
        del self.positions[symbol]
        self.pending.pop(symbol, None)

    def _quantity(self, reference, atr, prior_volume):
        cfg, costs = self.config, self.config.costs
        snapshot = self.account.get_account_snapshot()
        entry = costs.price(reference, TradeSide.BUY)
        stop = entry - atr * cfg.stop_atr
        if stop <= 0:
            return 0, 0.0
        loss_per_share = entry - costs.price(stop, TradeSide.SELL)
        available_risk = min(snapshot.total_equity * cfg.risk_per_trade,
                             snapshot.total_equity * cfg.max_open_risk - sum(p["planned_risk"] for p in self.positions.values()))
        upper = max(0, floor(min(snapshot.cash / entry, snapshot.total_equity * cfg.max_position_fraction / entry,
                                 prior_volume * cfg.max_volume_participation)))
        low, high = 0, upper
        while low < high:
            mid = (low + high + 1) // 2
            risk = mid * loss_per_share + 2 * costs.commission(mid)
            cash = mid * entry + costs.commission(mid)
            if risk <= available_risk and cash <= snapshot.cash:
                low = mid
            else:
                high = mid - 1
        return low, low * loss_per_share + 2 * costs.commission(low) if low else 0.0

    def run(self, dataset: IntradayDataset, *, observer=None) -> ReplayResult:
        """Optionally publish detached records after each completed minute/session.

        The observer records historical shadow evidence; it cannot change the
        strategy state. Observer failures abort the run instead of losing logs.
        """
        if self.used:
            raise ValueError("use a fresh replay instance for each run")
        self.used = True
        cfg, ny = self.config, ZoneInfo("America/New_York")
        if (cfg.opening_volume is not None and dataset.provenance.get("feed") != "sip"
                and dataset.provenance.get("source") != "SYNTHETIC_DEMO"):
            raise ValueError("opening volume replay requires declared SIP data or a labeled synthetic fixture")
        if not dataset.bars:
            raise ValueError("replay requires minute data")
        by_time, keys = {}, set()
        for bar in dataset.bars:
            validate_bar(bar)
            key = (bar.timestamp, bar.symbol)
            if key in keys:
                raise ValueError("duplicate symbol/timestamp")
            keys.add(key)
            by_time.setdefault(bar.timestamp, {})[bar.symbol] = bar
        symbols = sorted(set(b.symbol for b in dataset.bars) | set(dataset.provenance.get("symbols", ())))
        selector = OpeningVolumeSelector(symbols, cfg.opening_volume) if cfg.opening_volume else None
        offsets, previous_quality = {}, {}

        def emit(kind, at, session):
            if observer is None:
                return
            tables = dict(fills=self.fills, trades=self.trades, equity=self.equity,
                          decisions=self.decisions, daily=self.daily,
                          selections=selector.rows if selector else [])
            rows = {}
            for name, values in tables.items():
                rows[name] = [dict(row) for row in values[offsets.get(name, 0):]]
                offsets[name] = len(values)
            rows["quality"] = [dict(row) for key, row in self.issues.items()
                               if previous_quality.get(key) != row]
            previous_quality.update({key: dict(row) for key, row in self.issues.items()})
            observer(dict(kind=kind, as_of=at.isoformat(), session=session.session_id,
                          hypothetical=True, **rows))
        dates = [bar.timestamp.astimezone(ny).date() for bar in dataset.bars]
        requested_start = dataset.provenance.get("start")
        requested_end = dataset.provenance.get("end_exclusive")
        if bool(requested_start) != bool(requested_end):
            raise ValueError("source metadata must provide both start and end_exclusive")
        if requested_start:
            requested_start, requested_end = aware_time(requested_start), aware_time(requested_end)
            if requested_end <= requested_start:
                raise ValueError("invalid source request period")
            dates.extend((requested_start.astimezone(ny).date(), requested_end.astimezone(ny).date()))
        # The calendar library requires start < end, including one-session runs.
        # Pad its construction only, then select the actual requested sessions.
        first_day, last_day = min(dates), max(dates)
        calendar = load_xnys_calendar(first_day - timedelta(days=1), last_day + timedelta(days=1))
        sessions = tuple(s for s in calendar.sessions if first_day <= s.opens_at.astimezone(ny).date() <= last_day
                         and (not requested_start or (s.opens_at >= requested_start and s.closes_at <= requested_end)))
        if not sessions:
            raise ValueError("dataset contains no XNYS sessions")
        for symbol in symbols:
            self.bots[symbol] = IntradayBreakoutBot(cfg.adx_threshold)
            self.features[symbol] = StreamingBreakoutFeatures(cfg.atr_period, cfg.adx_period)
        accepted = 0
        for session in sessions:
            if selector:
                selector.begin_session(session)
            blocked, previous_volume = set(), {}
            self.windows = {symbol: [] for symbol in symbols}
            day_start = self.account.get_account_snapshot().total_equity
            loss_halted, missing_held = False, False
            active = cfg.decision_start is None or session.opens_at.astimezone(ny).date() >= cfg.decision_start
            cutoff = session.closes_at - timedelta(minutes=cfg.last_entry_minutes_before_close)
            flatten = session.closes_at - timedelta(minutes=cfg.flatten_minutes_before_close)
            t = session.opens_at
            while t < session.closes_at:
                current, end = by_time.get(t, {}), t + MINUTE
                if selector:
                    selector.observe_minute(t, current)
                accepted += len(current)
                # All available opens are marked before deterministic symbol-order
                # cash/risk allocation. Future highs, lows and volumes are not used.
                self.execution.set_fill_context(t, {s: b.open for s, b in current.items()})
                if self.account.get_account_snapshot().total_equity <= day_start * (1 - cfg.daily_loss_limit):
                    loss_halted = True
                for symbol in sorted(tuple(self.positions)):
                    if symbol not in current:
                        continue
                    pos, opening = self.positions[symbol], current[symbol].open
                    if pos["session"] != session.session_id or not pos["path_complete"]:
                        self._exit(symbol, opening, t, "data_gap_recovery")
                    elif opening <= pos["stop"]:
                        self._exit(symbol, opening, t, "gap_stop")
                    elif opening >= pos["target"]:
                        self._exit(symbol, opening, t, "gap_target")
                    elif loss_halted or t >= flatten:
                        self._exit(symbol, opening, t, "daily_loss_limit" if loss_halted else "scheduled_flatten")
                for symbol in sorted(tuple(self.pending)):
                    order = self.pending[symbol]
                    if t < order["eligible_at"]:
                        continue
                    self.pending.pop(symbol)
                    if order["side"] == "exit":
                        if symbol in self.positions and symbol in current:
                            self._exit(symbol, current[symbol].open, t, order["reason"], decision_at=order["decision_at"])
                        continue
                    reason = None
                    if symbol not in current:
                        reason = "missing_execution_bar"
                    elif loss_halted or missing_held:
                        reason = "account_halted"
                    elif symbol in blocked or order["session"] != session.session_id or t >= cutoff:
                        reason = "session_or_data_gate"
                    elif len(self.positions) >= cfg.max_positions:
                        reason = "maximum_positions"
                    quantity, risk = (0, 0.0) if reason else self._quantity(current[symbol].open, order["atr"], order["volume"])
                    if reason or quantity == 0:
                        self._decision(symbol, t, "REJECT_ENTRY", reason or "risk_cash_or_volume_budget")
                        continue
                    fill = self._fill(symbol, quantity, TradeSide.BUY, current[symbol].open, t, "orb_long", order["decision_at"])
                    if fill["status"] == "filled":
                        self.positions[symbol] = dict(entry=fill, quantity=quantity, planned_risk=risk,
                                                      stop=fill["price"] - order["atr"] * cfg.stop_atr,
                                                      target=fill["price"] + order["atr"] * cfg.target_atr,
                                                      session=session.session_id, path_complete=True)
                        if self.account.get_account_snapshot().total_equity <= day_start * (1 - cfg.daily_loss_limit):
                            loss_halted = True
                # Standing exits inside the minute: timing is an interval, not an
                # invented tick. Known opening gaps were handled before this step.
                for symbol in sorted(tuple(self.positions)):
                    if symbol not in current:
                        self.positions[symbol]["path_complete"] = False
                        missing_held = True
                        self._issue(session, symbol, "MISSING_HELD_BAR", end)
                        continue
                    pos, bar = self.positions[symbol], current[symbol]
                    # An entry whose friction is larger than its stop distance
                    # can immediately encounter its protective stop at this open.
                    if bar.open <= pos["stop"]:
                        self._exit(symbol, bar.open, t, "gap_stop")
                        continue
                    stop, target = bar.low <= pos["stop"], bar.high >= pos["target"]
                    if stop and target:
                        self._issue(session, symbol, "AMBIGUOUS_STOP_FIRST", end)
                    if stop or target:
                        self._exit(symbol, pos["stop"] if stop else pos["target"], end,
                                   "stop_loss" if stop else "take_profit", interval_end=end)
                for symbol in symbols:
                    if symbol not in current:
                        if symbol not in blocked:
                            self.features[symbol] = StreamingBreakoutFeatures(cfg.atr_period, cfg.adx_period)
                        blocked.add(symbol)
                        self._issue(session, symbol, "MISSING_MINUTE", end)
                        self.windows[symbol] = []
                        continue
                    bar = current[symbol]
                    self.portfolio.update_market_price(symbol, bar.close)
                    if bar.volume == 0:
                        blocked.add(symbol)
                        self._issue(session, symbol, "ZERO_VOLUME_MINUTE", end)
                        if symbol in self.positions:
                            self.positions[symbol]["path_complete"] = False
                            missing_held = True
                        self.features[symbol] = StreamingBreakoutFeatures(cfg.atr_period, cfg.adx_period)
                        self.windows[symbol] = []
                        continue
                    window = self.windows[symbol]
                    window.append(bar)
                    previous_volume[symbol] = bar.volume
                    if int((end - session.opens_at).total_seconds() / 60) % 5:
                        continue
                    self.windows[symbol] = []
                    if len(window) != 5 or window[0].timestamp != end - timedelta(minutes=5):
                        continue
                    aggregate = MarketContext(symbol, window[0].timestamp, "5m", window[0].open,
                                              max(b.high for b in window), min(b.low for b in window),
                                              window[-1].close, sum(b.volume for b in window))
                    features = self.features[symbol].add(aggregate, as_of=end)
                    if not active or loss_halted or missing_held or symbol in blocked or symbol in self.positions or end >= cutoff:
                        continue
                    if selector and symbol not in selector.selected:
                        continue
                    # The bot sees the completed five-minute close at its actual
                    # decision time; the range itself uses interval-start labels.
                    signal = self.bots[symbol].evaluate(replace(aggregate, timestamp=end), features)
                    if signal is None:
                        continue
                    if signal.direction != SignalDirection.LONG:
                        self._decision(symbol, end, "SKIP_SHORT", "long_only_baseline")
                        continue
                    self.pending[symbol] = dict(side="entry", session=session.session_id, atr=features.atr,
                                                volume=previous_volume[symbol], decision_at=end,
                                                eligible_at=end + timedelta(minutes=cfg.execution_delay_minutes))
                    self._decision(symbol, end, "QUEUE_LONG", "orb_breakout", atr=features.atr, adx=features.adx,
                                   prior_minute_volume=previous_volume[symbol],
                                   eligible_at=self.pending[symbol]["eligible_at"].isoformat())
                snapshot = self.account.get_account_snapshot()
                if snapshot.total_equity <= day_start * (1 - cfg.daily_loss_limit):
                    loss_halted = True
                    for symbol in self.positions:
                        self.pending[symbol] = dict(side="exit", reason="daily_loss_limit", decision_at=end,
                                                    eligible_at=end + timedelta(minutes=cfg.execution_delay_minutes))
                holdings = sum(p.market_value for p in self.portfolio.get_portfolio_snapshot().positions)
                if not isclose(snapshot.cash + holdings, snapshot.total_equity, abs_tol=1e-6):
                    raise AssertionError("account equity does not reconcile")
                self.equity.append(dict(timestamp=end.isoformat(), session=session.session_id,
                                        cash=snapshot.cash, holdings_value=holdings, equity=snapshot.total_equity,
                                        open_positions=len(self.positions), daily_loss_halted=loss_halted,
                                        marks_complete=all(s in current for s in self.positions)))
                t = end
                emit("MINUTE_COMPLETED", end, session)
            for symbol in tuple(self.pending):
                if self.pending[symbol]["side"] == "entry":
                    self._decision(symbol, session.closes_at, "CANCEL_ENTRY", "session_closed")
                self.pending.pop(symbol)
            for symbol in self.positions:
                self.positions[symbol]["path_complete"] = False
                self._issue(session, symbol, "UNRESOLVED_AT_CLOSE", session.closes_at)
            day_issues = [q for q in self.issues.values() if q["session"] == session.session_id]
            complete = not any(q["code"] in {"MISSING_MINUTE", "MISSING_HELD_BAR", "UNRESOLVED_AT_CLOSE", "ZERO_VOLUME_MINUTE"} for q in day_issues)
            ending = self.account.get_account_snapshot()
            self.daily.append(dict(session=session.session_id, session_open=session.opens_at.isoformat(),
                                   session_close=session.closes_at.isoformat(), starting_equity=day_start,
                                   ending_equity=ending.total_equity, net_change=ending.total_equity - day_start,
                                   cash=ending.cash, open_positions=len(self.positions), data_complete=complete,
                                   daily_loss_halted=loss_halted, decision_period=active))
            emit("SESSION_COMPLETED", session.closes_at, session)
        snapshot = self.account.get_account_snapshot()
        commissions = sum(f["commission"] for f in self.fills)
        cash_flow = sum(f["cash_delta"] for f in self.fills)
        if not isclose(snapshot.cash, cfg.initial_cash + cash_flow, abs_tol=1e-6):
            raise AssertionError("fill cash flows do not reconcile to ending cash")
        if not self.positions and not isclose(snapshot.total_equity - cfg.initial_cash,
                                             sum(t["net_pnl"] for t in self.trades), abs_tol=1e-6):
            raise AssertionError("closed trade PnL does not reconcile to account equity")
        complete = all(d["data_complete"] for d in self.daily) and not self.positions
        config = asdict(cfg)
        config["decision_start"] = cfg.decision_start.isoformat() if cfg.decision_start else None
        peak, drawdown = cfg.initial_cash, 0.0
        for row in self.equity:
            peak = max(peak, row["equity"])
            drawdown = max(drawdown, (peak - row["equity"]) / peak)
        summary = dict(task="INTRA-1A", runner_version="INTRA-1A:1", strategy="tanyuan_orb", side="long_only", config=config,
                       input=dataset.provenance, calendar_version=calendar.calendar_version,
                       decision_bars="5m", execution_bars="1m", opening_range_minutes=30,
                       allocation_order="LEXICOGRAPHIC_SYMBOL_AFTER_EXIT_AND_OPEN_MARKS",
                       fill_model="MODELED_SPREAD_SLIPPAGE_FEES_NOT_NBBO_OR_QUEUE",
                       status="COMPLETE_REPLAY" if complete else "INCOMPLETE_DATA_OR_UNRESOLVED_POSITIONS",
                       performance_admissible=complete and dataset.provenance.get("source") != "SYNTHETIC_DEMO",
                       effectiveness="NOT_EVALUATED", production_enabled=False,
                       input_bars=len(dataset.bars), regular_session_bars=accepted,
                       ignored_non_session_bars=len(dataset.bars) - accepted, symbols=symbols,
                       sessions=len(self.daily), trades=len(self.trades), ending_cash=snapshot.cash,
                       ending_equity=snapshot.total_equity, open_positions=len(self.positions),
                       modeled_equity_change=snapshot.total_equity - cfg.initial_cash,
                       net_pnl=snapshot.total_equity - cfg.initial_cash if complete else None,
                       total_commission=commissions, total_spread_cost=sum(f["spread_cost"] for f in self.fills),
                       total_slippage_cost=sum(f["slippage_cost"] for f in self.fills),
                       maximum_drawdown=drawdown if complete else None, accounting_reconciled=True)
        if selector:
            summary.update(task="INTRA-1B", runner_version="INTRA-1B:1",
                           selection_policy="OPENING_30M_OVER_PRIOR_SCHEDULED_OPENINGS_MEAN",
                           selection_decisions=len(selector.rows),
                           selected_symbol_sessions=sum(r["selected"] for r in selector.rows))
        return ReplayResult(summary, self.fills, self.trades, self.equity, self.daily, self.decisions,
                            sorted(self.issues.values(), key=lambda q: (q["session"], q["symbol"], q["code"])),
                            selector.rows if selector else [])
