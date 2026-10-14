"""Persistent scripted broker truth, with no sockets, URLs or credentials."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

from dx27.adapters.intraday.lifecycle_journal import LifecycleJournal, seal
from dx27.domains.intraday.order_lifecycle import BrokerSnapshot, OrderReport, OrderRequest, identifier, money, money_text


class ScriptedBroker:
    """Explicit cumulative outcomes for conformance, not a market/fill model.

    Revisions are simulator-only monotone counters, not claimed Alpaca fields.
    Each truth transition commits independently of the local order book.
    """

    def __init__(self, path, namespace, initial_cash):
        self.namespace = identifier(namespace)
        self.initial_cash = money(initial_cash)
        cash = money_text(self.initial_cash)
        self.journal = LifecycleJournal(path, dict(contract="P2-H:1", role="SCRIPTED_BROKER",
                                                  namespace=namespace, initial_cash=cash),
                                        dict(cash=cash, positions={}, orders={}, submit_calls=0, cancel_calls=0))

    def submit(self, client_order_id, request: OrderRequest):
        state = deepcopy(self.journal.state)
        state["submit_calls"] += 1
        if client_order_id in state["orders"]:
            existing = state["orders"][client_order_id]
            if existing["request"] != request.to_dict():
                raise ValueError("scripted broker client ID conflict")
            self.journal.save(state, dict(kind="SUBMIT_LOOKUP", client_order_id=client_order_id))
            return OrderReport(**existing["report"])
        report = OrderReport("sim:" + client_order_id + ":1", client_order_id,
                             "sim-" + seal(client_order_id)[:32], 1,
                             request.symbol, request.side, request.quantity, "accepted")
        state["orders"][client_order_id] = dict(request=request.to_dict(), report=report.to_dict())
        self.journal.save(state, dict(kind="ACCEPTED", client_order_id=client_order_id))
        return report

    def latest(self, client_order_id):
        item = self.journal.state["orders"].get(client_order_id)
        return OrderReport(**item["report"]) if item else None

    def advance(self, client_order_id, status, filled_quantity=0, filled_notional=0, fee=0):
        previous = self.latest(client_order_id)
        if previous is None:
            raise ValueError("scripted order not found")
        report = replace(previous, event_id="sim:" + client_order_id + ":" + str(previous.revision + 1),
                         revision=previous.revision + 1, status=status, filled_quantity=filled_quantity,
                         filled_notional=money(filled_notional), fee=money(fee))
        report.validate()
        if (report.status, report.filled_quantity, report.filled_notional, report.fee) == (
                previous.status, previous.filled_quantity, previous.filled_notional, previous.fee):
            return previous
        dq = report.filled_quantity - previous.filled_quantity
        dn, df = report.filled_notional - previous.filled_notional, report.fee - previous.fee
        if dq < 0 or dn < 0 or df < 0 or (dq == 0 and dn) or (dq > 0 and dn <= 0):
            raise ValueError("scripted cumulative outcomes must advance")
        if previous.status in {"filled", "rejected"} and status != previous.status:
            raise ValueError("scripted terminal order cannot reopen")
        if previous.status in {"canceled", "expired"} and status not in {previous.status, "filled"}:
            raise ValueError("scripted canceled/expired order cannot reopen")
        state = deepcopy(self.journal.state)
        symbol = report.symbol
        if report.side.value == "buy":
            state["cash"] = money_text(Decimal(state["cash"]) - dn - df)
            quantity = state["positions"].get(symbol, 0) + dq
        else:
            state["cash"] = money_text(Decimal(state["cash"]) + dn - df)
            quantity = state["positions"].get(symbol, 0) - dq
        if quantity:
            state["positions"][symbol] = quantity
        else:
            state["positions"].pop(symbol, None)
        state["orders"][client_order_id]["report"] = report.to_dict()
        self.journal.save(state, dict(kind="SCRIPTED_REPORT", report=report.to_dict()))
        return report

    def cancel(self, client_order_id):
        state = deepcopy(self.journal.state)
        state["cancel_calls"] += 1
        self.journal.save(state, dict(kind="CANCEL_CALL", client_order_id=client_order_id))
        report = self.latest(client_order_id)
        if report is None:
            raise ValueError("scripted cancel order not found")
        if report.status in {"filled", "canceled", "rejected", "expired"}:
            return report
        return self.advance(client_order_id, "canceled", report.filled_quantity, report.filled_notional, report.fee)

    def snapshot(self):
        state = deepcopy(self.journal.state)
        return BrokerSnapshot(Decimal(state["cash"]), state["positions"],
                              tuple(OrderReport(**order["report"]) for order in state["orders"].values()))

    def close(self):
        self.journal.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
