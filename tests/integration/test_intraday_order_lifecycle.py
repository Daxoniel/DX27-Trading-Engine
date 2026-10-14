from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
import sqlite3
import subprocess
import sys

import pytest

from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.application.offline_order_execution import OfflineOrderExecution
from dx27.core.models.trade_intent import TradeIntent, TradeSide
from dx27.domains.intraday.order_lifecycle import BrokerSnapshot, OrderRequest


@contextmanager
def session(root, cash=10_000):
    with OfflineOrderBook(root / "book.sqlite3", "test", cash) as book:
        with ScriptedBroker(root / "broker.sqlite3", "test", cash) as broker:
            execution = OfflineOrderExecution(book, broker)
            yield book, broker, execution


def request(name="entry", *, side="buy", quantity=10, price=100, fee=1, symbol="SPY"):
    return OrderRequest(name, "tanyuan_orb", symbol, TradeSide(side), quantity, Decimal(str(price)), Decimal(str(fee)))


def place(book, execution, value=None):
    cid = book.prepare(value or request())["client_order_id"]
    execution.submit(cid)
    return cid


def test_partial_fill_deduplication_out_of_order_completion_and_cash_are_exact(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        assert execution.reconcile()["ready"]
        cid = place(book, execution)
        accepted = broker.latest(cid)
        partial = broker.advance(cid, "partial", 4, "399.96", "0.35")
        assert book.apply(partial) == "APPLIED"
        before = book.snapshot()
        assert before["cash"] == "9599.69" and before["positions"] == {"SPY": 4}
        assert book.apply(partial) == "DUPLICATE" and book.snapshot() == before
        same = replace(partial, event_id="different-transport-event")
        assert book.apply(same) == "SAME_REVISION"
        filled = broker.advance(cid, "filled", 10, "999.9", "0.35")
        book.apply(filled)
        assert book.apply(replace(accepted, event_id="delayed-accepted-event")) == "STALE"
        assert Decimal(book.snapshot()["cash"]) == Decimal("8999.75")
        assert book.snapshot()["positions"] == {"SPY": 10}
        assert book.order(cid)["state"] == "FILLED"
        assert execution.reconcile()["ready"]
        assert book.order(cid)["client_order_id"] == cid
        execution.submit(cid)  # A resolved order never gets another submit call.
        assert broker.journal.state["submit_calls"] == 1


def test_rejection_expiration_and_partial_cancel_release_only_unfilled_reservations(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        rejected = place(book, execution)
        book.apply(broker.advance(rejected, "rejected"))
        assert book.snapshot()["cash"] == "10000" and book.snapshot()["positions"] == {}
        expired = place(book, execution, request("expired"))
        book.apply(broker.advance(expired, "expired"))
        cid = place(book, execution, request("partial-cancel"))
        book.apply(broker.advance(cid, "partial", 4, "400", "0.35"))
        execution.cancel(cid)
        assert book.order(cid)["state"] == "CANCELED"
        assert book.snapshot()["positions"] == {"SPY": 4}
        assert book.snapshot()["cash"] == "9599.65"
        execution.cancel(cid)
        assert broker.journal.state["cancel_calls"] == 1
        exit_id = place(book, execution, request("exit", side="sell", quantity=4, price=101))
        book.apply(broker.advance(exit_id, "filled", 4, "404", "0.35"))
        assert book.snapshot()["positions"] == {}
        assert book.snapshot()["cash"] == "10003.3"
        assert execution.reconcile()["ready"]


@pytest.mark.parametrize("accepted_remotely", [False, True])
def test_submission_timeout_is_never_retried_and_not_found_stays_unresolved(tmp_path, monkeypatch, accepted_remotely):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = book.prepare(request())["client_order_id"]
        original = broker.submit

        def timeout(cid, value):
            if accepted_remotely:
                original(cid, value)
            raise TimeoutError("synthetic lost acknowledgement")

        monkeypatch.setattr(broker, "submit", timeout)
        assert execution.submit(cid)["state"] == "UNKNOWN"
        assert not book.ready
        with pytest.raises(ValueError, match="paused"):
            book.prepare(request("new-entry"))
        monkeypatch.setattr(broker, "submit", lambda *args: pytest.fail("blind retry"))
        execution.submit(cid)
        receipt = execution.reconcile()
        assert receipt["ready"] is accepted_remotely
        assert book.order(cid)["state"] == ("ACCEPTED" if accepted_remotely else "UNKNOWN")
        assert broker.journal.state["submit_calls"] == int(accepted_remotely)


def test_restart_forces_reconciliation_and_missing_then_rediscovered_report_resolves(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        assert book.reconcile(BrokerSnapshot(Decimal(10_000), {}, ()))["ready"] is False
        assert book.order(cid)["state"] == "UNKNOWN"
        assert execution.reconcile()["ready"]
        assert book.order(cid)["state"] == "ACCEPTED"
    with session(tmp_path) as (book, broker, execution):
        assert not book.ready
        with pytest.raises(ValueError, match="paused"):
            book.prepare(request("after-restart"))
        assert execution.reconcile()["ready"]
        execution.submit(cid)
        assert broker.journal.state["submit_calls"] == 1


def test_cancel_timeout_and_fill_cancel_race_reconcile_without_phantom_refunds(tmp_path, monkeypatch):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        book.apply(broker.advance(cid, "partial", 4, "400", "0.35"))
        original = broker.cancel

        def lost_cancel(cid):
            original(cid)
            raise TimeoutError("lost cancel reply")

        monkeypatch.setattr(broker, "cancel", lost_cancel)
        assert execution.cancel(cid)["state"] == "CANCEL_UNKNOWN"
        assert not book.ready
        execution.cancel(cid)
        assert broker.journal.state["cancel_calls"] == 1
        assert execution.reconcile()["ready"]
        assert book.order(cid)["state"] == "CANCELED"
        assert book.snapshot()["cash"] == "9599.65" and book.snapshot()["positions"] == {"SPY": 4}
        second = place(book, execution, request("fill-race"))
        monkeypatch.setattr(broker, "cancel", original)
        broker.advance(second, "filled", 10, "1000", "0.35")  # Fill happened before cancellation arrived.
        execution.cancel(second)
        assert book.order(second)["state"] == "FILLED"
        assert book.snapshot()["positions"] == {"SPY": 14}
        assert execution.reconcile()["ready"]


def test_cash_and_share_reservations_cover_created_and_partial_orders(tmp_path):
    with session(tmp_path, cash=1_001) as (book, broker, execution):
        execution.reconcile()
        created = book.prepare(request())["client_order_id"]
        with pytest.raises(ValueError, match="unreserved cash"):
            book.prepare(request("double-budget", quantity=1))
        execution.submit(created)
        book.apply(broker.advance(created, "partial", 4, "400", "0.35"))
        with pytest.raises(ValueError, match="unreserved cash"):
            book.prepare(request("partial-budget", quantity=1))
        execution.cancel(created)
        with pytest.raises(ValueError, match="unreserved shares"):
            book.prepare(request("oversell", side="sell", quantity=5))
        book.prepare(request("reserved-exit", side="sell", quantity=4))
        with pytest.raises(ValueError, match="unreserved shares"):
            book.prepare(request("double-exit", side="sell", quantity=1))


@pytest.mark.parametrize("change", ["event_collision", "revision_collision", "quantity_regression", "identity", "terminal_reopen", "repricing"])
def test_conflicting_reports_pause_without_changing_cash_or_positions(tmp_path, change):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        report = broker.advance(cid, "filled", 10, "1000", "0.35")
        book.apply(report)
        changes = {
            "event_collision": dict(fee=Decimal("0.4")),
            "revision_collision": dict(event_id="other-event", fee=Decimal("0.4")),
            "quantity_regression": dict(event_id="new-event", revision=4, status="partial", filled_quantity=5, filled_notional=Decimal("500")),
            "identity": dict(event_id="new-event", revision=4, symbol="QQQ"),
            "terminal_reopen": dict(event_id="new-event", revision=4, status="partial"),
            "repricing": dict(event_id="new-event", revision=4, filled_notional=Decimal("1001")),
        }
        before = book.snapshot()
        with pytest.raises(ValueError, match="conflicting"):
            book.apply(replace(report, **changes[change]))
        after = book.snapshot()
        assert after["cash"] == before["cash"] and after["positions"] == before["positions"]
        assert after["orders"] == before["orders"] and after["integrity_halt"] is not None
        assert not execution.reconcile()["ready"]


def test_valid_reported_budget_breach_is_recorded_then_pauses_new_intents(tmp_path):
    with session(tmp_path, cash=1_001) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        book.apply(broker.advance(cid, "filled", 10, "1010", "0.35"))
        assert book.snapshot()["cash"] == "-9.35" and book.snapshot()["positions"] == {"SPY": 10}
        assert not execution.reconcile()["ready"]
        with pytest.raises(ValueError, match="paused"):
            book.prepare(request("ignore-negative-cash"))


@pytest.mark.parametrize("mismatch", ["cash", "positions", "incomplete", "unowned", "stale"])
def test_reconciliation_gates_new_submissions_on_incomplete_or_mismatched_truth(tmp_path, mismatch):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        accepted = broker.latest(cid)
        book.apply(broker.advance(cid, "filled", 10, "1000", "0.35"))
        truth = broker.snapshot()
        if mismatch == "cash":
            truth = replace(truth, cash=truth.cash + 1)
        elif mismatch == "positions":
            truth = replace(truth, positions={"SPY": 11})
        elif mismatch == "incomplete":
            truth = replace(truth, complete=False)
        elif mismatch == "unowned":
            unknown = replace(accepted, event_id="foreign-event", client_order_id="foreign-order", broker_order_id="foreign-broker")
            truth = replace(truth, orders=truth.orders + (unknown,))
        else:
            truth = replace(truth, orders=(accepted,))
        receipt = book.reconcile(truth)
        assert receipt["ready"] is False
        with pytest.raises(ValueError, match="paused"):
            book.prepare(request("new-intent"))
        assert execution.reconcile()["ready"]


@pytest.mark.parametrize("remote_fill", [False, True])
def test_process_dies_after_durable_claim_or_remote_fill_and_never_blindly_resubmits(tmp_path, remote_fill):
    script = """
import os, sys
from pathlib import Path
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.application.offline_order_execution import OfflineOrderExecution
from dx27.domains.intraday.order_lifecycle import OrderRequest
root=Path(sys.argv[1])
with OfflineOrderBook(root/'book.sqlite3', 'test', 10000) as book, ScriptedBroker(root/'broker.sqlite3', 'test', 10000) as broker:
    execution=OfflineOrderExecution(book, broker)
    execution.reconcile()
    cid=book.prepare(OrderRequest('entry','tanyuan_orb','SPY','buy',10,100,1))['client_order_id']
    book.claim_submission(cid)
    if sys.argv[2]=='1':
        broker.submit(cid, OrderRequest('entry','tanyuan_orb','SPY','buy',10,100,1))
        broker.advance(cid,'partial',4,400,'0.35')
    os._exit(17)
"""
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(int(remote_fill))], timeout=30)
    assert child.returncode == 17
    with session(tmp_path) as (book, broker, execution):
        cid = next(iter(book.snapshot()["orders"]))
        assert book.order(cid)["state"] == "SUBMITTING" and not book.ready
        receipt = execution.reconcile()
        assert receipt["ready"] is remote_fill
        assert book.order(cid)["state"] == ("PARTIAL" if remote_fill else "UNKNOWN")
        assert book.snapshot()["positions"] == ({"SPY": 4} if remote_fill else {})
        assert book.snapshot()["cash"] == ("9599.65" if remote_fill else "10000")
        execution.submit(cid)
        assert broker.journal.state["submit_calls"] == int(remote_fill)


def test_identity_manifest_single_writer_and_state_corruption_are_refused(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        book.prepare(request())
        with pytest.raises(sqlite3.OperationalError):
            OfflineOrderBook(tmp_path / "book.sqlite3", "test", 10_000)
        with pytest.raises(ValueError, match="different request"):
            book.prepare(request(quantity=9))
    with pytest.raises(ValueError, match="mismatch"):
        OfflineOrderBook(tmp_path / "book.sqlite3", "different", 10_000)
    with sqlite3.connect(tmp_path / "book.sqlite3") as db:
        db.execute("UPDATE metadata SET value='{}' WHERE key='state'")
    with pytest.raises(ValueError, match="integrity"):
        OfflineOrderBook(tmp_path / "book.sqlite3", "test", 10_000)


@pytest.mark.parametrize("quantity", [True, None, 1.5, float("inf"), float("nan"), -1])
def test_fractional_notional_and_invalid_intents_are_not_silently_coerced(quantity):
    intent = TradeIntent("tanyuan_orb", "SPY", TradeSide.BUY, quantity=quantity)
    with pytest.raises(ValueError):
        OrderRequest.from_intent(intent, "invalid", 100)


def test_real_adapter_is_not_accepted_and_namespace_is_bound(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        with pytest.raises(TypeError, match="local scripted"):
            OfflineOrderExecution(book, object())
        with ScriptedBroker(tmp_path / "different.sqlite3", "other", 10_000) as other:
            with pytest.raises(ValueError, match="mismatch"):
                OfflineOrderExecution(book, other)


def test_unsent_intent_can_be_abandoned_without_a_broker_call_and_budget_is_released(tmp_path):
    with session(tmp_path, cash=1001) as (book, broker, execution):
        execution.reconcile()
        cid = book.prepare(request())["client_order_id"]
        assert execution.cancel(cid)["state"] == "ABANDONED"
        execution.submit(cid)
        assert broker.journal.state["submit_calls"] == broker.journal.state["cancel_calls"] == 0
        assert execution.reconcile()["ready"]
        other = place(book, execution, request("replacement"))
        assert other != cid and book.order(other)["state"] == "ACCEPTED"


def test_snapshot_outage_pauses_created_orders_until_full_reconciliation(tmp_path, monkeypatch):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = book.prepare(request())["client_order_id"]
        original = broker.snapshot
        monkeypatch.setattr(broker, "snapshot", lambda: (_ for _ in ()).throw(TimeoutError("outage")))
        assert execution.reconcile()["issues"] == ["snapshot_unavailable"]
        with pytest.raises(ValueError, match="paused"):
            execution.submit(cid)
        assert book.order(cid)["state"] == "CREATED" and broker.journal.state["submit_calls"] == 0
        monkeypatch.setattr(broker, "snapshot", original)
        assert execution.reconcile()["ready"]
        execution.submit(cid)
        assert broker.journal.state["submit_calls"] == 1


def test_late_terminal_fee_update_and_fill_after_cancel_are_applied_exactly_once(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        book.apply(broker.advance(cid, "partial", 4, 400, "0.35"))
        execution.cancel(cid)
        late_fill = broker.advance(cid, "filled", 10, 1000, "0.35")
        book.apply(late_fill)
        fee_update = broker.advance(cid, "filled", 10, 1000, "0.7")
        book.apply(fee_update)
        book.apply(fee_update)
        assert book.snapshot()["cash"] == "8999.3" and book.snapshot()["positions"] == {"SPY": 10}
        assert execution.reconcile()["ready"]


def test_late_fill_rechecks_reserved_exit_shares_before_submission(tmp_path):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        entry = place(book, execution)
        book.apply(broker.advance(entry, "filled", 10, 1000, "0.35"))
        first_exit = place(book, execution, request("first-exit", side="sell"))
        book.apply(broker.advance(first_exit, "partial", 4, 400, "0.35"))
        execution.cancel(first_exit)
        replacement = book.prepare(request("replacement-exit", side="sell", quantity=6))["client_order_id"]
        book.apply(broker.advance(first_exit, "canceled", 5, 500, "0.35"))
        assert book.snapshot()["positions"] == {"SPY": 5}
        with pytest.raises(ValueError, match="reserved shares changed"):
            execution.submit(replacement)
        assert book.order(replacement)["state"] == "CREATED" and broker.journal.state["submit_calls"] == 2


def test_pending_sell_fees_cannot_be_spent_by_an_already_prepared_buy(tmp_path):
    with session(tmp_path, cash=1002) as (book, broker, execution):
        execution.reconcile()
        entry = place(book, execution, request(quantity=1))
        book.apply(broker.advance(entry, "filled", 1, 100, "0.35"))
        buy = book.prepare(request("new-buy", quantity=9, fee=1))["client_order_id"]
        sell = book.prepare(request("sell", side="sell", quantity=1, fee=1))["client_order_id"]
        # Both fees are reserved; the second intent must not steal the first's cash.
        with pytest.raises(ValueError, match="reserved cash changed"):
            execution.submit(buy)
        execution.cancel(sell)
        execution.submit(buy)
        assert book.order(buy)["state"] == "ACCEPTED"


def test_failed_report_storage_pauses_until_broker_fill_is_reconciled(tmp_path, monkeypatch):
    with session(tmp_path) as (book, broker, execution):
        execution.reconcile()
        cid = place(book, execution)
        partial = broker.advance(cid, "partial", 4, 400, "0.35")
        original = book.journal.save
        monkeypatch.setattr(book.journal, "save", lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("storage unavailable")))
        with pytest.raises(sqlite3.OperationalError):
            book.apply(partial)
        assert not book.ready
        assert book.snapshot()["cash"] == "10000" and book.snapshot()["positions"] == {}
        monkeypatch.setattr(book.journal, "save", original)
        with pytest.raises(ValueError, match="paused"):
            book.prepare(request("after-storage-failure"))
        assert execution.reconcile()["ready"]
        assert book.snapshot()["cash"] == "9599.65" and book.snapshot()["positions"] == {"SPY": 4}
        assert broker.journal.state["submit_calls"] == 1


def test_terminal_order_late_fee_budget_cannot_be_reallocated_to_another_buy(tmp_path):
    with session(tmp_path, cash="2001.35") as (book, broker, execution):
        execution.reconcile()
        first = place(book, execution)
        book.apply(broker.advance(first, "filled", 10, 1000, "0.35"))
        assert book.snapshot()["cash"] == "1001"
        with pytest.raises(ValueError, match="unreserved cash"):
            book.prepare(request("double-spend-late-fee"))
        second = book.prepare(request("fully-budgeted", fee="0.35"))["client_order_id"]
        book.apply(broker.advance(first, "filled", 10, 1000, 1))
        execution.submit(second)
        book.apply(broker.advance(second, "filled", 10, 1000, "0.35"))
        assert book.snapshot()["cash"] == "0" and book.snapshot()["positions"] == {"SPY": 20}
        assert execution.reconcile()["ready"]
