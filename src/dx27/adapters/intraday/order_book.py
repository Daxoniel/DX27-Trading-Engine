"""Persistent whole-share order book for offline lifecycle acceptance only."""

from copy import deepcopy
from decimal import Decimal
import sqlite3

from dx27.adapters.intraday.lifecycle_journal import LifecycleJournal, canonical, seal
from dx27.domains.intraday.order_lifecycle import (
    BrokerSnapshot, OrderReport, OrderRequest, TERMINAL, UNCERTAIN, identifier, money, money_text,
)


class OfflineOrderBook:
    def __init__(self, path, namespace, initial_cash):
        self.namespace = identifier(namespace)
        initial_cash = money(initial_cash)
        self.initial_cash = initial_cash
        self.journal = LifecycleJournal(path, dict(contract="P2-H:1", role="OFFLINE_ORDER_BOOK",
                                                  namespace=namespace, initial_cash=money_text(initial_cash)),
                                        dict(cash=money_text(initial_cash), positions={}, orders={}, reports={},
                                             integrity_halt=None, reconciliation_issue=None))
        # A process restart always requires a new complete reconciliation.
        self.reconciled = False

    def snapshot(self):
        return deepcopy(self.journal.state)

    @property
    def ready(self):
        state = self.journal.state
        return (self.reconciled and state["integrity_halt"] is None and state["reconciliation_issue"] is None
                and not any(o["state"] in UNCERTAIN for o in state["orders"].values())
                and Decimal(state["cash"]) >= 0 and all(q >= 0 for q in state["positions"].values()))

    def halt(self, reason):
        state = self.snapshot()
        state["integrity_halt"] = reason
        self.reconciled = False
        self.journal.save(state, dict(kind="INTEGRITY_HALT", reason=reason))

    @staticmethod
    def _reservations(state):
        cash, shares = Decimal(0), {}
        for order in state["orders"].values():
            terminal = order["state"].lower() in TERMINAL
            if order["state"] == "ABANDONED" or (terminal and not order["filled_quantity"]):
                continue
            request = order["request"]
            cash += max(Decimal(0), Decimal(request["fee_budget"]) - Decimal(order["fee"]))
            if terminal:
                continue  # Late fill commissions still consume this fee budget.
            remaining = request["quantity"] - order["filled_quantity"]
            if request["side"] == "buy":
                cash += remaining * Decimal(request["reservation_price"])
            else:
                shares[request["symbol"]] = shares.get(request["symbol"], 0) + remaining
        return cash, shares

    def prepare(self, request: OrderRequest):
        cid = "dx27h-" + seal(self.namespace + ":" + request.intent_id)[:32]
        state = self.snapshot()
        if cid in state["orders"]:
            if state["orders"][cid]["request"] != request.to_dict():
                self.halt("intent_identity_conflict")
                raise ValueError("intent ID already belongs to a different request")
            return deepcopy(state["orders"][cid])
        if not self.ready:
            raise ValueError("new intents paused until complete consistent reconciliation")
        cash_reserved, shares_reserved = self._reservations(state)
        if request.side.value == "buy":
            if request.quantity * request.reservation_price + request.fee_budget > Decimal(state["cash"]) - cash_reserved:
                raise ValueError("insufficient unreserved cash")
        elif request.quantity > state["positions"].get(request.symbol, 0) - shares_reserved.get(request.symbol, 0):
            raise ValueError("insufficient unreserved shares")
        order = dict(client_order_id=cid, request=request.to_dict(), state="CREATED", broker_order_id=None,
                     revision=0, broker_status=None, filled_quantity=0, filled_notional="0", fee="0",
                     cancel_requested=False, last_report=None)
        state["orders"][cid] = order
        self.journal.save(state, dict(kind="INTENT_PREPARED", client_order_id=cid))
        return deepcopy(order)

    def order(self, client_order_id):
        return deepcopy(self.journal.state["orders"][client_order_id])

    def claim_submission(self, client_order_id):
        state = self.snapshot()
        order = state["orders"][client_order_id]
        if order["state"] != "CREATED":
            return False
        if not self.ready:
            raise ValueError("submission paused until reconciliation")
        cash_reserved, shares_reserved = self._reservations(state)
        request = order["request"]
        if request["side"] == "buy" and cash_reserved > Decimal(state["cash"]):
            raise ValueError("reserved cash changed before submission")
        if request["side"] == "sell" and shares_reserved.get(request["symbol"], 0) > state["positions"].get(request["symbol"], 0):
            raise ValueError("reserved shares changed before submission")
        order["state"] = "SUBMITTING"
        self.journal.save(state, dict(kind="SUBMISSION_STARTED", client_order_id=client_order_id))
        return True

    def claim_cancel(self, client_order_id):
        state = self.snapshot()
        order = state["orders"][client_order_id]
        if order["state"] == "CREATED":
            order["state"] = "ABANDONED"
            self.journal.save(state, dict(kind="INTENT_ABANDONED", client_order_id=client_order_id))
            return False
        if order["state"] not in {"ACCEPTED", "PARTIAL"}:
            return False
        order.update(state="CANCEL_PENDING", cancel_requested=True)
        self.journal.save(state, dict(kind="CANCEL_STARTED", client_order_id=client_order_id))
        return True

    def uncertain(self, client_order_id, *, cancel=False):
        state = self.snapshot()
        order = state["orders"][client_order_id]
        if order["state"] != ("CANCEL_PENDING" if cancel else "SUBMITTING"):
            raise ValueError("cannot mark a resolved order uncertain")
        order["state"] = "CANCEL_UNKNOWN" if cancel else "UNKNOWN"
        self.journal.save(state, dict(kind=order["state"], client_order_id=client_order_id))

    def apply(self, report: OrderReport):
        try:
            return self._apply(report)
        except (OSError, sqlite3.Error):
            self.reconciled = False
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            self.halt("invalid_or_conflicting_report")
            raise ValueError("invalid or conflicting cumulative order report; new intents paused") from None

    def _apply(self, report):
        report.validate()
        state, body = self.snapshot(), report.to_dict()
        prior_event = state["reports"].get(report.event_id)
        if prior_event is not None:
            if prior_event["report"] != body:
                raise ValueError("event ID conflict")
            return "DUPLICATE"
        order = state["orders"][report.client_order_id]
        request = order["request"]
        if (order["state"] in {"CREATED", "ABANDONED"} or (report.symbol, report.side.value, report.quantity)
                != (request["symbol"], request["side"], request["quantity"])
                or order["broker_order_id"] not in (None, report.broker_order_id)):
            raise ValueError("order identity conflict")
        if report.revision < order["revision"]:
            disposition = "STALE"
        elif report.revision == order["revision"]:
            without_id = lambda value: {k: v for k, v in value.items() if k != "event_id"}
            if without_id(body) != without_id(order["last_report"]):
                raise ValueError("revision conflict")
            disposition = "SAME_REVISION"
        else:
            previous_q = order["filled_quantity"]
            previous_n, previous_f = Decimal(order["filled_notional"]), Decimal(order["fee"])
            dq, dn, df = report.filled_quantity - previous_q, report.filled_notional - previous_n, report.fee - previous_f
            if dq < 0 or dn < 0 or df < 0 or (dq == 0 and dn != 0) or (dq > 0 and dn <= 0):
                raise ValueError("cumulative fills/costs cannot regress or be repriced")
            previous_status = order["broker_status"]
            if previous_status in TERMINAL:
                allowed = {previous_status}
                if previous_status in {"canceled", "expired"}:
                    allowed.add("filled")  # Authoritative cancellation/fill race.
                if report.status not in allowed:
                    raise ValueError("terminal order cannot be reopened")
            order.update(broker_order_id=report.broker_order_id, revision=report.revision,
                         broker_status=report.status, filled_quantity=report.filled_quantity,
                         filled_notional=money_text(report.filled_notional), fee=money_text(report.fee), last_report=body)
            if report.status in TERMINAL:
                order.update(state=report.status.upper(), cancel_requested=False)
            elif order["cancel_requested"]:
                order["state"] = "CANCEL_PENDING"
            else:
                order["state"] = report.status.upper()
            side = 1 if request["side"] == "buy" else -1
            state["cash"] = money_text(Decimal(state["cash"]) - side * dn - df)
            quantity = state["positions"].get(request["symbol"], 0) + side * dq
            if quantity:
                state["positions"][request["symbol"]] = quantity
            else:
                state["positions"].pop(request["symbol"], None)
            # Valid executions remain recorded even when they violate local caps.
            if ((request["side"] == "buy" and report.filled_notional > report.filled_quantity * Decimal(request["reservation_price"]))
                    or report.fee > Decimal(request["fee_budget"]) or Decimal(state["cash"]) < 0
                    or quantity < 0):
                state["integrity_halt"] = "reported_execution_exceeds_local_budget"
            disposition = "APPLIED"
        state["reports"][report.event_id] = dict(report=body, disposition=disposition)
        self.journal.save(state, dict(kind="REPORT", event_id=report.event_id, disposition=disposition))
        return disposition

    def reconcile(self, snapshot: BrokerSnapshot):
        self.reconciled = False
        if not snapshot.complete:
            return self.pause_reconciliation("incomplete_snapshot")
        reports = {report.client_order_id: report for report in snapshot.orders}
        if len(reports) != len(snapshot.orders):
            self.halt("duplicate_orders_in_snapshot")
            raise ValueError("snapshot must contain one latest report per order")
        issues = []
        for cid, report in reports.items():
            if cid not in self.journal.state["orders"]:
                issues.append("unowned_broker_order")
                continue
            if report.revision < self.order(cid)["revision"]:
                issues.append("stale_order_snapshot")
            self.apply(report)
        state = self.snapshot()
        for cid, order in state["orders"].items():
            if order["state"] in {"CREATED", "ABANDONED"}:
                continue
            if cid not in reports:
                issues.append("order_not_found")
                if order["state"].lower() not in TERMINAL:
                    order["state"] = "CANCEL_UNKNOWN" if order["cancel_requested"] else "UNKNOWN"
            elif (order["state"] in {"UNKNOWN", "SUBMITTING"} and not order["cancel_requested"]
                  and reports[cid].revision == order["revision"]):
                # A complete authoritative lookup may rediscover the same report
                # after a previous not-found response; no fill is applied twice.
                order["state"] = order["broker_status"].upper()
            if order["state"] in UNCERTAIN:
                issues.append("unresolved_order")
        if Decimal(state["cash"]) != snapshot.cash:
            issues.append("cash_mismatch")
        if state["positions"] != snapshot.positions:
            issues.append("position_mismatch")
        issues = sorted(set(issues))
        state["reconciliation_issue"] = ",".join(issues) if issues else None
        self.journal.save(state, dict(kind="RECONCILIATION", issues=issues))
        self.reconciled = not issues
        return dict(ready=self.ready, issues=issues,
                    integrity_halt=state["integrity_halt"], cash_matches="cash_mismatch" not in issues,
                    positions_match="position_mismatch" not in issues)

    def pause_reconciliation(self, reason):
        self.reconciled = False
        state = self.snapshot()
        state["reconciliation_issue"] = reason
        self.journal.save(state, dict(kind="RECONCILIATION_BLOCKED", reason=reason))
        return dict(ready=False, issues=[reason])

    def close(self):
        self.journal.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
