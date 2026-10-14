"""Clocked offline fills feeding the existing ORB minute decision/risk loop."""

from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
from math import ceil, isclose

from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.adapters.simulated.execution import SimulatedExecutionAdapter
from dx27.application.intraday_replay import IntradayLedgerReplay, MINUTE
from dx27.application.offline_order_execution import OfflineOrderExecution
from dx27.core.models.account_snapshot import AccountSnapshot
from dx27.core.models.trade_intent import TradeIntent, TradeSide
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.order_lifecycle import OrderRequest, TERMINAL, UNCERTAIN
from dx27.domains.intraday.risk_budget import plan_quantity


CENT_PRECISION = Decimal("0.00000001")


def _amount(value, *, ceiling=False):
    return Decimal(str(value)).quantize(CENT_PRECISION, rounding=ROUND_CEILING if ceiling else ROUND_HALF_EVEN)


class _BookAccount:
    def __init__(self, book, portfolio):
        self.book, self.portfolio = book, portfolio

    def get_account_snapshot(self):
        cash = float(self.book.journal.state["cash"])
        holdings = sum(p.market_value for p in self.portfolio.get_portfolio_snapshot().positions)
        return AccountSnapshot(cash + holdings, cash, cash)


class ClosedLoopReplay(IntradayLedgerReplay):
    """Fresh offline reconstruction only; never rerun against an existing broker.

    Signal/indicator/calendar logic is inherited. The clocked driver overrides
    execution, quantities and actual-position accounting, not strategy rules.
    """

    def __init__(self, config, profile, book: OfflineOrderBook, broker: ScriptedBroker, *, ingress=None):
        super().__init__(config)
        self.ingress = ingress
        self.profile = profile or HistoricalExecutionProfile()
        self.book, self.broker = book, broker
        self.coordinator = OfflineOrderExecution(book, broker)
        if book.journal.state["orders"] or broker.journal.state["orders"] or book.initial_cash != _amount(config.initial_cash):
            raise ValueError("closed-loop reconstruction requires fresh matching simulator state")
        if not self.coordinator.reconcile()["ready"]:
            raise ValueError("initial offline reconciliation failed")
        self.account = _BookAccount(book, self.portfolio)
        self.execution = SimulatedExecutionAdapter(self.account, self.portfolio, costs=config.costs)
        self.orders, self.execution_events, self.lots, self.waiting_exits = {}, [], {}, {}
        self.marks, self.entry_number, self.session_now = {}, 0, None
        self.as_of = None
        self.completed_round_trips = 0

    def _active(self, symbol=None, side=None):
        result = []
        for cid, meta in self.orders.items():
            order = self.book.journal.state["orders"][cid]
            if order["state"].lower() in TERMINAL or order["state"] == "ABANDONED":
                continue
            if (symbol is None or meta["symbol"] == symbol) and (side is None or meta["side"] == side):
                result.append((cid, meta, order))
        return result

    def _entry_data_ready(self, symbol, at):
        return self.ingress is None or self.ingress.ready(symbol, at)

    def _entries_paused(self, at=None, symbol=None):
        return not self.book.ready or (at is not None and not self._entry_data_ready(symbol, at))

    def _maximum_price(self, reference):
        return self.config.costs.price(reference, TradeSide.BUY) * (1 + self.profile.entry_reservation_buffer_bps / 10_000)

    def _quantity(self, reference, atr, prior_volume):
        if not self.book.ready:
            return 0, 0.0
        active = self._active(side="buy")
        symbols = set(self.positions) | {m["symbol"] for _, m, _ in active}
        if len(symbols) >= self.config.max_positions:
            return 0, 0.0
        reserved, _ = self.book._reservations(self.book.journal.state)
        snapshot = self.account.get_account_snapshot()
        open_risk = sum(p["planned_risk"] for p in self.positions.values())
        open_risk += sum(m["planned_risk"] * (o["request"]["quantity"] - o["filled_quantity"]) / o["request"]["quantity"] for _, m, o in active)
        maximum = self._maximum_price(reference) if self.profile.entry_reservation_buffer_bps else None
        return plan_quantity(self.config, cash=max(0, snapshot.cash - float(reserved)), equity=snapshot.total_equity,
                             open_risk=open_risk, reference=reference, atr=atr, prior_volume=prior_volume,
                             maximum_entry_price=maximum)

    def _event(self, kind, at, cid=None, **values):
        self.execution_events.append(dict(kind=kind, received_at=at.isoformat(), client_order_id=cid, **values))

    def _fill(self, symbol, quantity, side, reference, at, reason, decision_at=None, interval_end=None, **context):
        if not self.book.ready:
            self._decision(symbol, at, "REJECT_ENTRY" if side == TradeSide.BUY else "WAIT_EXIT", "unreconciled_orders")
            return dict(status="queued")
        cap = self._maximum_price(reference) if side == TradeSide.BUY else self.config.costs.price(reference, side)
        fee = _amount(self.config.costs.commission(quantity))
        intent = TradeIntent("tanyuan_orb", symbol, side, quantity=quantity, reason=(reason,))
        identity = f"{symbol}:{side.value}:{at.isoformat().replace('+', '_')}:{len(self.orders) + 1}"
        request = OrderRequest.from_intent(intent, identity, _amount(cap, ceiling=True), fee)
        cid = self.book.prepare(request)["client_order_id"]
        meta = dict(symbol=symbol, side=side.value, reason=reason, decision_at=decision_at,
                    session=context.get("session", self.session_now.session_id), atr=context.get("atr"),
                    planned_risk=context.get("planned_risk", 0), path_complete=True,
                    next_at=at + timedelta(minutes=self.profile.entry_delay_minutes if side == TradeSide.BUY else self.profile.exit_delay_minutes),
                    chunk=max(1, ceil(quantity * self.profile.fill_fraction)), executions=[], received=0,
                    reconcile_at=None, initial_interval_end=interval_end)
        self.orders[cid] = meta
        self._event("INTENT_CREATED", at, cid, symbol=symbol, side=side.value, quantity=quantity,
                    planned_risk=context.get("planned_risk", 0), planning_equity=self.account.get_account_snapshot().total_equity)
        self.book.claim_submission(cid)
        uncertain = False
        if side == TradeSide.BUY:
            self.entry_number += 1
            uncertain = bool(self.profile.uncertain_every_nth_entry and self.entry_number % self.profile.uncertain_every_nth_entry == 0)
        if not uncertain or self.profile.uncertainty_mode == "accepted":
            report = self.broker.submit(cid, request)
        if uncertain:
            self.book.uncertain(cid)
            meta["reconcile_at"] = at + timedelta(minutes=self.profile.reconciliation_delay_minutes)
            self._event("SUBMIT_UNKNOWN", at, cid)
        else:
            self._receive(cid, report, at)
        if side == TradeSide.BUY and self.profile.reject_every_nth_entry and self.entry_number % self.profile.reject_every_nth_entry == 0 and self.broker.latest(cid) is not None:
            report = self.broker.advance(cid, "rejected")
            if not uncertain:
                self._receive(cid, report, at)
        if meta["next_at"] <= at:
            self._advance(cid, reference, at, interval_end)
        return dict(status="queued", client_order_id=cid)

    def _receive(self, cid, report, at):
        disposition = self.book.apply(report)
        self._event("REPORT", at, cid, revision=report.revision, state=report.status, disposition=disposition)
        if self.profile.duplicate_reports:
            duplicate = self.book.apply(report)
            if duplicate != "DUPLICATE":
                raise AssertionError("duplicate report changed its disposition")
        self._deliver_facts(cid, at)

    def _deliver_facts(self, cid, at):
        meta, order = self.orders[cid], self.book.order(cid)
        while meta["received"] < len(meta["executions"]):
            fact = meta["executions"][meta["received"]]
            if fact["cumulative_quantity"] > order["filled_quantity"]:
                break
            self._record_fact(cid, fact, at)
            meta["received"] += 1

    def _oracle_equity(self):
        state = self.broker.journal.state
        return float(state["cash"]) + sum(q * self.marks[s] for s, q in state["positions"].items())

    def _advance(self, cid, reference, at, interval_end=None):
        meta, previous = self.orders[cid], self.broker.latest(cid)
        if previous is None or previous.status in TERMINAL:
            return
        q = min(meta["chunk"], previous.quantity - previous.filled_quantity)
        side = TradeSide(meta["side"])
        price = self.config.costs.price(reference, side)
        notional = _amount(price * q)
        total_quantity = previous.filled_quantity + q
        fee = _amount(self.config.costs.commission(total_quantity))
        delta_fee = fee - previous.fee
        request = self.book.order(cid)["request"]
        state = self.broker.journal.state
        too_high = side == TradeSide.BUY and price > float(request["reservation_price"])
        cash_bad = side == TradeSide.BUY and notional + delta_fee > Decimal(state["cash"])
        shares_bad = side == TradeSide.SELL and q > state["positions"].get(meta["symbol"], 0)
        if too_high or cash_bad or shares_bad:
            report = self.broker.advance(cid, "canceled" if previous.filled_quantity else "rejected",
                                         previous.filled_quantity, previous.filled_notional, previous.fee)
            self._event("EXECUTION_BUDGET_REFUSAL", at, cid)
        else:
            cash_before, equity_before = float(state["cash"]), self._oracle_equity()
            report = self.broker.advance(cid, "filled" if total_quantity == previous.quantity else "partial",
                                         total_quantity, previous.filled_notional + notional, fee)
            meta["executions"].append(dict(quantity=q, notional=float(notional), fee=float(delta_fee),
                                            reference=reference, timestamp=at, interval_end=interval_end,
                                            cumulative_quantity=total_quantity, revision=report.revision,
                                            cash_before=cash_before, cash_after=float(self.broker.journal.state["cash"]),
                                            equity_before=equity_before))
        meta["next_at"] = at + MINUTE
        if meta["reconcile_at"] is None:
            self._receive(cid, report, at)

    def _record_fact(self, cid, fact, received_at):
        meta = self.orders[cid]
        q, reference, side = fact["quantity"], fact["reference"], TradeSide(meta["side"])
        spread = reference * q * self.config.costs.spread_bps / 20_000
        slippage = reference * q * self.config.costs.slippage_bps / 10_000
        row = dict(fill_id=len(self.fills) + 1, client_order_id=cid, symbol=meta["symbol"], side=side.value,
                   timestamp=fact["timestamp"].isoformat(), received_at=received_at.isoformat(),
                   decision_at=meta["decision_at"].isoformat() if meta["decision_at"] else None,
                   reason=meta["reason"], requested_quantity=self.book.order(cid)["request"]["quantity"],
                   quantity=q, status="filled", reference_price=reference, price=fact["notional"] / q,
                   commission=fact["fee"], spread_cost=spread, slippage_cost=slippage,
                   equity_before=fact["equity_before"], cash_before=fact["cash_before"],
                   cash_after=fact["cash_after"], cash_delta=((-1 if side == TradeSide.BUY else 1) * fact["notional"] - fact["fee"]),
                   interval_start=(fact["timestamp"] - MINUTE).isoformat() if fact["interval_end"] else fact["timestamp"].isoformat(),
                   interval_end=fact["interval_end"].isoformat() if fact["interval_end"] else fact["timestamp"].isoformat(),
                   time_precision="BAR_INTERVAL" if fact["interval_end"] else "MODELED_OPEN")
        self.fills.append(row)
        symbol = meta["symbol"]
        if side == TradeSide.BUY:
            self.portfolio.buy(symbol, q, row["price"])
            lot = self.lots.setdefault(symbol, dict(quantity=0, notional=0.0, reference_notional=0.0, fee=0.0,
                                                    spread=0.0, slippage=0.0, entry_time=row["timestamp"], fill_ids=(),
                                                    atr=meta["atr"], session=meta["session"], path_complete=meta["path_complete"]))
            lot.update(quantity=lot["quantity"] + q, notional=lot["notional"] + fact["notional"],
                       reference_notional=lot["reference_notional"] + q * reference, fee=lot["fee"] + fact["fee"],
                       spread=lot["spread"] + spread, slippage=lot["slippage"] + slippage,
                       fill_ids=lot["fill_ids"] + (row["fill_id"],))
            self._mark_position(symbol)
        else:
            lot, position = self.lots[symbol], self.positions[symbol]
            fraction = q / lot["quantity"]
            entry_n, entry_f = lot["notional"] * fraction, lot["fee"] * fraction
            gross = q * reference - lot["reference_notional"] * fraction
            net = fact["notional"] - entry_n - entry_f - fact["fee"]
            total_spread, total_slip = lot["spread"] * fraction + spread, lot["slippage"] * fraction + slippage
            if not isclose(net, gross - entry_f - fact["fee"] - total_spread - total_slip, abs_tol=1e-6):
                raise AssertionError("clocked trade costs do not reconcile")
            self.trades.append(dict(symbol=symbol, quantity=q, entry_time=lot["entry_time"], exit_time=row["timestamp"],
                                    entry_fill_id=lot["fill_ids"][0], entry_fill_ids=lot["fill_ids"], exit_fill_id=row["fill_id"],
                                    entry_price=entry_n / q, exit_price=row["price"], gross_pnl=gross,
                                    commission=entry_f + fact["fee"], spread_cost=total_spread, slippage_cost=total_slip,
                                    net_pnl=net, planned_stop_risk=position["planned_risk"] * fraction,
                                    exit_reason=meta["reason"], path_complete=position["path_complete"]))
            self.portfolio.sell(symbol, q, row["price"])
            lot["quantity"] -= q
            for field in ("notional", "reference_notional", "fee", "spread", "slippage"):
                lot[field] *= 1 - fraction
            if not lot["quantity"]:
                self.completed_round_trips += 1
                del self.lots[symbol]
                del self.positions[symbol]
                self.pending.pop(symbol, None)
                self.waiting_exits.pop(symbol, None)
            else:
                self._mark_position(symbol)
        self.portfolio.update_market_price(symbol, self.marks.get(symbol, reference))

    def _mark_position(self, symbol):
        lot = self.lots[symbol]
        average = lot["notional"] / lot["quantity"]
        stop = average - lot["atr"] * self.config.stop_atr
        risk = lot["quantity"] * (average - self.config.costs.price(stop, TradeSide.SELL)) + lot["fee"] + self.config.costs.commission(lot["quantity"])
        old = self.positions.get(symbol)
        complete = old["path_complete"] if old else lot["path_complete"]
        self.positions[symbol] = dict(quantity=lot["quantity"], planned_risk=risk, stop=stop,
                                      target=average + lot["atr"] * self.config.target_atr,
                                      session=lot["session"], path_complete=complete)

    def _cancel(self, cid, at):
        meta, order = self.orders[cid], self.book.order(cid)
        if order["state"] in {"ACCEPTED", "PARTIAL"}:
            self.book.claim_cancel(cid)
            report = self.broker.cancel(cid)
            if self.profile.lose_cancel_replies:
                self.book.uncertain(cid, cancel=True)
                meta["reconcile_at"] = at + timedelta(minutes=self.profile.reconciliation_delay_minutes)
                self._event("CANCEL_UNKNOWN", at, cid)
            else:
                self._receive(cid, report, at)
        elif order["state"] == "CREATED":
            self.book.claim_cancel(cid)

    def _exit(self, symbol, reference, at, reason, *, decision_at=None, interval_end=None):
        for cid, _, _ in self._active(symbol, "buy"):
            self._cancel(cid, at)
        if self._active(symbol, "sell"):
            return
        if not self.book.ready:
            self.waiting_exits[symbol] = reason
            self._decision(symbol, at, "WAIT_EXIT", "unreconciled_orders", exit_reason=reason)
            return
        self.waiting_exits.pop(symbol, None)
        self._fill(symbol, self.positions[symbol]["quantity"], TradeSide.SELL, reference, at, reason,
                   decision_at, interval_end)

    def _reconcile_due(self, at, *, force=False):
        due = [cid for cid, meta in self.orders.items() if meta["reconcile_at"] is not None and (force or meta["reconcile_at"] <= at)]
        if not due:
            return
        result = self.coordinator.reconcile()
        self._event("RECONCILIATION", at, ready=result["ready"], issues=tuple(result["issues"]))
        for cid, meta in self.orders.items():
            if cid in due or self.book.order(cid)["state"] not in UNCERTAIN:
                meta["reconcile_at"] = None
        for cid in self.orders:
            self._deliver_facts(cid, at)

    def _before_minute(self, at, current, session, day_start, loss_halted, cutoff, flatten):
        self.session_now, self.as_of = session, at
        self.marks.update({s: b.open for s, b in current.items()})
        self._reconcile_due(at)
        if self.ingress is not None:
            for cid, meta, _ in self._active(side="buy"):
                if not self._entry_data_ready(meta["symbol"], at):
                    self._cancel(cid, at)
        loss_halted = loss_halted or self.account.get_account_snapshot().total_equity <= day_start * (1 - self.config.daily_loss_limit)
        for cid, meta, _ in self._active(side="buy"):
            position, bar = self.positions.get(meta["symbol"]), current.get(meta["symbol"])
            protective = position is not None and (not position["path_complete"] or position["session"] != session.session_id or
                                                   (bar is not None and (bar.open <= position["stop"] or bar.open >= position["target"])))
            if loss_halted or at >= cutoff or meta["session"] != session.session_id or protective:
                self._cancel(cid, at)
        for symbol in sorted(tuple(self.waiting_exits)):
            if symbol in self.positions and symbol in current and self.book.ready:
                self._exit(symbol, current[symbol].open, at, self.waiting_exits[symbol])
        active = sorted(self._active(), key=lambda item: (item[1]["side"] == "buy", item[1]["symbol"], item[0]))
        for cid, meta, _ in active:
            if meta["next_at"] > at or meta["symbol"] not in current:
                continue
            if meta["side"] == "buy" and loss_halted:
                self._cancel(cid, at)
                continue
            self._advance(cid, current[meta["symbol"]].open, at)
            loss_halted = loss_halted or self.account.get_account_snapshot().total_equity <= day_start * (1 - self.config.daily_loss_limit)
        return loss_halted

    def _after_minute(self, at, current, session):
        self.marks.update({s: b.close for s, b in current.items()})
        for cid, meta, _ in self._active(side="buy"):
            bar = current.get(meta["symbol"])
            if bar is None or bar.volume == 0:
                self._cancel(cid, at)
        state = self.book.journal.state
        truth = self.broker.journal.state
        reconciled = state["cash"] == truth["cash"] and state["positions"] == truth["positions"] and self.book.ready
        row = self.equity[-1]
        row.update(orders_reconciled=reconciled, broker_equity=self._oracle_equity(),
                   active_orders=len(self._active()), reserved_cash=float(self.book._reservations(state)[0]),
                   reported_positions=dict(state["positions"]), broker_positions=dict(truth["positions"]),
                   reported_open_risk=sum(p["planned_risk"] for p in self.positions.values()),
                   entry_reserved_risk=sum(m["planned_risk"] * (o["request"]["quantity"] - o["filled_quantity"]) / o["request"]["quantity"]
                                           for _, m, o in self._active(side="buy")))
        if self.ingress is not None:
            state_at = self.ingress.state_at(at)
            row["ingress_connected"] = bool(state_at and state_at.connected)
            row["ingress_recovering"] = bool(not state_at or state_at.recovering)
            row["ingress_blocked_symbols"] = state_at.blocked_symbols if state_at else tuple()
        row["marks_complete"] = row["marks_complete"] and reconciled and all(s in current for s in truth["positions"])
        if reconciled and not isclose(row["equity"], row["broker_equity"], abs_tol=1e-6):
            raise AssertionError("strategy account and independent simulated broker differ")

    def _after_session(self, session):
        for cid, _, _ in self._active(side="buy"):
            self._cancel(cid, session.closes_at)
        # Never manufacture an early acknowledgement just because history ends.
        self._reconcile_due(session.closes_at)
        for cid, meta, _ in self._active():
            meta["path_complete"] = False
            self._issue(session, meta["symbol"], "UNRESOLVED_ORDER_AT_CLOSE", session.closes_at)

    def _execution_complete(self):
        return not self._active() and self.book.ready and not self.broker.journal.state["positions"] and (self.ingress is None or self.ingress.complete)

    def run(self, dataset, *, observer=None, minute_source=None):
        result = super().run(dataset, observer=observer, minute_source=minute_source)
        result.summary.update(task="P2-H2", runner_version="P2-H2:1", execution_profile=asdict(self.profile),
                              underlying_strategy="INTRA-1B" if self.config.opening_volume else "INTRA-1A",
                              order_count=len(self.orders), active_orders=len(self._active()),
                              completed_round_trips=self.completed_round_trips, realized_exit_fragments=len(self.trades),
                              simulator_submit_calls=self.broker.journal.state["submit_calls"],
                              broker_ending_cash=float(self.broker.journal.state["cash"]),
                              broker_ending_positions=dict(self.broker.journal.state["positions"]),
                              real_broker_orders_enabled=False, strategy_execution_feedback_verified=True,
                              financial_precision="DECIMAL_8_FOR_EXECUTION_NOTIONAL_AND_FEES")
        if any(not row["marks_complete"] for row in self.equity):
            result.summary["performance_admissible"] = False
        peak, drawdown = self.config.initial_cash, 0.0
        for row in self.equity:
            peak = max(peak, row["broker_equity"])
            drawdown = max(drawdown, (peak - row["broker_equity"]) / peak)
        result.summary["broker_maximum_drawdown"] = drawdown if result.summary["status"] == "COMPLETE_REPLAY" else None
        if self.ingress is not None:
            result.summary.update(task="P2-H4", runner_version="P2-H4:1", market_ingress=self.ingress.receipt())
            result.quality.extend(dict(session=None, symbol=r.symbol, code="INGRESS_" + r.disposition,
                first_at=r.as_of.isoformat(), last_at=r.as_of.isoformat(), count=1)
                for r in self.ingress.records if r.critical)
        return result
