"""Run scripted offline P2-H cases and optional historical intent-trace checks."""

import argparse
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
import json
from pathlib import Path
import sqlite3

from dx27.adapters.intraday.lifecycle_journal import seal
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.application.offline_order_execution import OfflineOrderExecution
from dx27.core.models.trade_intent import TradeIntent, TradeSide
from dx27.domains.intraday.order_lifecycle import BrokerSnapshot, OrderRequest, money_text


PRECISION = Decimal("0.00000001")


def _require(condition, message):
    if not condition:
        raise ValueError("conformance failed: " + message)


@contextmanager
def _pair(root, namespace, cash):
    root = Path(root)
    with OfflineOrderBook(root / "orders.sqlite3", namespace, cash) as book:
        with ScriptedBroker(root / "scripted-broker.sqlite3", namespace, cash) as broker:
            yield book, broker, OfflineOrderExecution(book, broker)


def _request(name, *, side="buy", quantity=10, price=100):
    return OrderRequest(name, "tanyuan_orb", "SPY", side, quantity, price, 1)


def _receipt(book, broker):
    state = book.snapshot()
    return dict(cash=state["cash"], positions=state["positions"], ready=book.ready,
                order_states={cid: order["state"] for cid, order in state["orders"].items()},
                orders=len(state["orders"]), submit_calls=broker.journal.state["submit_calls"],
                cancel_calls=broker.journal.state["cancel_calls"],
                integrity_halt=state["integrity_halt"], order_audit_chain=book.journal.chain,
                broker_audit_chain=broker.journal.chain)


def run_fault_cases(root):
    results = {}
    for name in ("partial_cancel", "reject_expire", "submit_reply_lost", "submit_not_found",
                 "cancel_reply_lost", "fill_cancel_race", "cash_mismatch", "budget_breach"):
        with _pair(Path(root) / name, "demo:" + name, 1001 if name == "budget_breach" else 10_000) as (book, broker, execution):
            _require(execution.reconcile()["ready"], "initial reconciliation")
            cid = book.prepare(_request("first"))["client_order_id"]
            if name in {"submit_reply_lost", "submit_not_found"}:
                original = broker.submit

                def lost_reply(client_id, request):
                    if name == "submit_reply_lost":
                        original(client_id, request)
                    raise TimeoutError("scripted submit uncertainty")

                broker.submit = lost_reply
                _require(execution.submit(cid)["state"] == "UNKNOWN", "unknown submit state")
                execution.submit(cid)
                resolved = execution.reconcile()["ready"]
                _require(resolved == (name == "submit_reply_lost"), "lookup outcome")
                _require(broker.journal.state["submit_calls"] == int(name == "submit_reply_lost"), "no blind resend")
            else:
                execution.submit(cid)
                if name == "reject_expire":
                    book.apply(broker.advance(cid, "rejected"))
                    other = book.prepare(_request("expiry"))["client_order_id"]
                    execution.submit(other)
                    book.apply(broker.advance(other, "expired"))
                    _require(book.snapshot()["cash"] == "10000" and not book.snapshot()["positions"], "reject/expiry have no fills")
                elif name in {"partial_cancel", "cancel_reply_lost"}:
                    partial = broker.advance(cid, "partial", 4, 400, "0.35")
                    book.apply(partial)
                    before = book.snapshot()
                    book.apply(partial)
                    _require(book.snapshot() == before, "duplicate report has no effect")
                    if name == "cancel_reply_lost":
                        original = broker.cancel

                        def lost_cancel(client_id):
                            original(client_id)
                            raise TimeoutError("scripted cancel uncertainty")

                        broker.cancel = lost_cancel
                    execution.cancel(cid)
                    execution.cancel(cid)
                    _require(execution.reconcile()["ready"], "cancellation reconciliation")
                    _require(book.order(cid)["state"] == "CANCELED" and book.snapshot()["positions"] == {"SPY": 4}, "partial cancellation preserves fills")
                    _require(book.snapshot()["cash"] == "9599.65" and broker.journal.state["cancel_calls"] == 1, "no phantom refund or repeat cancel")
                elif name == "fill_cancel_race":
                    broker.advance(cid, "filled", 10, 1000, "0.35")
                    execution.cancel(cid)
                    _require(book.order(cid)["state"] == "FILLED" and execution.reconcile()["ready"], "fill wins cancel race")
                elif name == "cash_mismatch":
                    truth = broker.snapshot()
                    _require(not book.reconcile(replace(truth, cash=truth.cash + 1))["ready"], "cash mismatch pauses")
                    _require(execution.reconcile()["ready"], "consistent truth resolves mismatch")
                else:
                    book.apply(broker.advance(cid, "filled", 10, 1010, "0.35"))
                    _require(book.snapshot()["cash"] == "-9.35" and not execution.reconcile()["ready"], "actual overspend recorded and paused")
            results[name] = dict(passed=True, **_receipt(book, broker))

    # Independent truth was committed while the local book only has SUBMITTING.
    path = Path(root) / "restart_after_remote_partial"
    with _pair(path, "demo:restart", 10_000) as (book, broker, execution):
        execution.reconcile()
        cid = book.prepare(_request("first"))["client_order_id"]
        book.claim_submission(cid)
        broker.submit(cid, _request("first"))
        broker.advance(cid, "partial", 4, 400, "0.35")
    with _pair(path, "demo:restart", 10_000) as (book, broker, execution):
        _require(not book.ready and book.order(cid)["state"] == "SUBMITTING", "restart must reconcile")
        _require(execution.reconcile()["ready"] and book.order(cid)["state"] == "PARTIAL", "remote partial recovered")
        execution.submit(cid)
        _require(broker.journal.state["submit_calls"] == 1 and book.snapshot()["cash"] == "9599.65", "restart did not resend")
        results["restart_after_remote_partial"] = dict(passed=True, **_receipt(book, broker))
    return results


def read_shadow_trace(path):
    """Read-only verified P1-H journal; never reprice old orders at a real broker."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        item = db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        if item is None:
            raise ValueError("source shadow manifest missing")
        manifest = json.loads(item[0])
        _require(manifest.get("mode") == "RECORDED_HISTORICAL_SHADOW" and manifest.get("broker_orders_enabled") is False, "historical source contract")
        chain, sequence, fills, final = "0" * 64, 0, [], None
        for seq, key, payload, digest in db.execute("SELECT sequence, frame_key, payload, chain FROM frames ORDER BY sequence"):
            sequence += 1
            _require(seq == sequence and digest == seal(chain + "\n" + key + "\n" + payload), "source shadow integrity")
            frame = json.loads(payload)
            if final is not None:
                raise ValueError("source has records after finalization")
            fills.extend(frame.get("fills", []))
            if frame["kind"] == "RUN_COMPLETED":
                final = frame["summary"]
            chain = digest
        _require(final is not None and final["status"] == "COMPLETE_REPLAY" and final["open_positions"] == 0, "complete flat historical source required")
    return fills, final, seal(item[0] + "\n" + chain)


def run_historical_trace(source, state_directory):
    fills, summary, source_hash = read_shadow_trace(source)
    _require(len({f["fill_id"] for f in fills}) == len(fills), "unique source fill IDs")
    partials = 0
    with _pair(state_directory, "trace:" + source_hash, summary["config"]["initial_cash"]) as (book, broker, execution):
        _require(execution.reconcile()["ready"], "historical initial/resume reconciliation")
        calls_before = broker.journal.state["submit_calls"]
        for fill in fills:
            price = Decimal(str(fill["price"])).quantize(PRECISION, rounding=ROUND_CEILING)
            fee = Decimal(str(fill["commission"])).quantize(PRECISION, rounding=ROUND_HALF_EVEN)
            intent = TradeIntent("tanyuan_orb", fill["symbol"], TradeSide(fill["side"]), quantity=fill["quantity"])
            value = OrderRequest.from_intent(intent, "fill:" + str(fill["fill_id"]), price, fee)
            cid = book.prepare(value)["client_order_id"]
            execution.submit(cid)
            if book.order(cid)["state"] == "FILLED":
                continue
            total = (Decimal(str(fill["price"])) * value.quantity).quantize(PRECISION, rounding=ROUND_HALF_EVEN)
            if value.quantity > 1:
                count = value.quantity // 2
                amount = (total * count / value.quantity).quantize(PRECISION, rounding=ROUND_HALF_EVEN)
                partial_fee = (fee / 2).quantize(PRECISION, rounding=ROUND_HALF_EVEN)
                report = broker.advance(cid, "partial", count, amount, partial_fee)
                book.apply(report)
                before = book.snapshot()
                book.apply(report)
                _require(book.snapshot() == before, "historical duplicate partial is economically idempotent")
                partials += 1
            book.apply(broker.advance(cid, "filled", value.quantity, total, fee))
        _require(execution.reconcile()["ready"], "historical final reconciliation")
        state = book.snapshot()
        residual = Decimal(state["cash"]) - Decimal(str(summary["ending_cash"]))
        _require(abs(residual) < Decimal("0.000001") and not state["positions"], "trace matches original modeled cash and final positions")
        _require(len(state["orders"]) == len(fills) and all(o["state"] == "FILLED" for o in state["orders"].values()), "all historical orders complete")
        return dict(source_trace_sha256=source_hash, source_input=summary["input"], source_task=summary["task"],
                    source_fills=len(fills), partial_reports_in_this_run=partials,
                    new_submit_calls=broker.journal.state["submit_calls"] - calls_before,
                    modeled_cash_residual=money_text(residual),
                    same_final_modeled_account=True, **_receipt(book, broker))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new offline acceptance directory")
    parser.add_argument("--source-journal", help="optional completed P1-H historical journal")
    parser.add_argument("--state-directory", help="reuse matching historical order/broker state for recovery")
    args = parser.parse_args(argv)
    try:
        if args.state_directory and not args.source_journal:
            raise ValueError("state-directory requires a historical source journal")
        root = Path(args.output)
        root.mkdir(parents=True, exist_ok=False)
        cases = run_fault_cases(root / "cases")
        report = dict(task="P2-H", contract="P2-H:1", status="PASS_OFFLINE_CONFORMANCE",
                      cases=cases, scripted_fault_cases=len(cases), real_broker_orders_enabled=False,
                      realtime_data_verified=False, effectiveness="NOT_EVALUATED")
        if args.source_journal:
            report["historical_trace"] = run_historical_trace(args.source_journal, args.state_directory or root / "trace-state")
        (root / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (root / "report.md").write_text(
            "# P2-H offline order lifecycle\n\n"
            f"Scripted fault cases passed: {len(cases)}. All orders and reports are local simulations.\n\n"
            "Stable client IDs, durable submission claims, cumulative partial-fill accounting,\n"
            "duplicate/stale report handling, cancellation and restart reconciliation are checked.\n"
            "Not-found submission outcomes stay paused and are never blindly resubmitted.\n\n"
            "See acceptance.json for per-case state, ledger balances and audit seals. Historical\n"
            "trace checks split fixed prior modeled fills; they do not rerun strategy decisions\n"
            "under changed execution, establish profitability or test actual Alpaca behavior.\n",
            encoding="utf-8")
        print(json.dumps(dict(status=report["status"], cases=len(cases), output=str(root))))
        return 0
    except (ValueError, OSError, TypeError, KeyError, sqlite3.DatabaseError) as exc:
        parser.exit(1, f"offline conformance failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
