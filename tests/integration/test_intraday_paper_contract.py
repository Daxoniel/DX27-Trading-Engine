"""Credential-free recorded paper contract acceptance; never broker I/O."""

from decimal import Decimal

import pytest

from dx27.adapters.alpaca.paper_contract import (
    PAPER_ENDPOINT, DisabledPaperGateway, PaperContractError, normalize_order as parse_order,
    normalize_trade_update as parse_update, recorded_snapshot, timestamp_revision,
)
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.application.paper_contract_review import apply_recorded_update, reconcile_recording, review_admission
from dx27.domains.intraday.order_lifecycle import OrderRequest

STAMP = "2025-02-03T15:00:00.123456789Z"
LATER = "2025-02-03T15:00:01.123456789Z"


def normalize_order(raw, *, cumulative_fee):
    # Fixture execution evidence is deliberately separate from rounded averages.
    return parse_order(raw, cumulative_fee=cumulative_fee,
                       cumulative_notional=str(Decimal(raw["filled_qty"]) * 100))


def normalize_trade_update(raw, *, cumulative_fee):
    return parse_update(raw, cumulative_fee=cumulative_fee,
                        cumulative_notional=str(Decimal(raw["order"]["filled_qty"]) * 100))


def order(cid="client-1", **changes):
    result = dict(id="broker-1", client_order_id=cid, symbol="SPY", side="buy",
                  qty="4", filled_qty="2", filled_avg_price="100", status="partially_filled",
                  updated_at=STAMP, asset_class="us_equity", type="market", time_in_force="day",
                  extended_hours=False, notional=None, order_class="simple", legs=None)
    return dict(result, **changes)


def bundle(raw):
    return dict(endpoint=PAPER_ENDPOINT, complete=True, coherent=True, captured_at=LATER,
                account={"currency": "USD", "cash": "799.9"}, positions=[dict(symbol="SPY", qty="2", side="long", asset_class="us_equity")],
                orders=[raw], cumulative_fees={raw["id"]: "0.1"}, cumulative_notionals={raw["id"]: "200"})


def prepared(path):
    book = OfflineOrderBook(path, "paper-contract-test", 1000)
    empty = dict(endpoint=PAPER_ENDPOINT, complete=True, coherent=True, captured_at=STAMP,
                 account={"currency": "USD", "cash": "1000"}, positions=[], orders=[], cumulative_fees={}, cumulative_notionals={})
    assert reconcile_recording(book, empty)["ready"]
    request = OrderRequest("intent-1", "orb", "SPY", "buy", 4, Decimal(100), Decimal(1))
    cid = book.prepare(request)["client_order_id"]
    assert book.claim_submission(cid)
    book.uncertain(cid)
    return book, cid


def admission(book, **changes):
    values = dict(endpoint=PAPER_ENDPOINT, account=dict(status="ACTIVE", currency="USD", trading_blocked=False,
                  account_blocked=False, trade_suspended_by_user=False),
                  clock=dict(is_open=True, timestamp=LATER),
                  asset=dict(symbol="SPY", status="active", tradable=True, **{"class": "us_equity"}),
                  symbol="SPY", captured_at=LATER, now=LATER)
    return review_admission(book, **dict(values, **changes))


def test_rest_stream_identity_and_nanosecond_ordering():
    raw = order()
    report = normalize_order(raw, cumulative_fee="0.1")
    update = dict(event="partial_fill", order=raw, timestamp=LATER, qty="999", price="999")
    assert normalize_trade_update(update, cumulative_fee="0.1") == report
    assert report.filled_quantity == 2 and report.filled_notional == Decimal(200)
    assert normalize_order(order(updated_at="2025-02-03T15:00:00.123456790Z"), cumulative_fee="0.1").revision == report.revision + 1
    assert normalize_order(dict(raw, unused="ignored"), cumulative_fee="0.1") == report


@pytest.mark.parametrize("changes", [
    {"status": "pending_cancel"}, {"status": "replaced"}, {"status": "done_for_day"},
    {"qty": "0.5"}, {"qty": True}, {"qty": "1e2"}, {"filled_qty": "5"},
    {"filled_avg_price": "NaN"}, {"filled_avg_price": "0"},
    {"filled_qty": "0", "filled_avg_price": "100"}, {"status": "filled"},
    {"asset_class": "crypto"}, {"type": "limit"}, {"time_in_force": "gtc"},
    {"extended_hours": True}, {"notional": "400"}, {"order_class": "bracket"},
    {"legs": [{}]}, {"updated_at": "2025-02-03T15:00:00+00:00"},
    {"updated_at": "2025-02-30T15:00:00Z"}, {"symbol": "SECRET PAYLOAD"},
])
def test_unsupported_orders_fail_redacted(changes):
    with pytest.raises(PaperContractError) as exc:
        normalize_order(order(**changes), cumulative_fee="0.1")
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("fee", [None, True, "NaN", "-1", "0.000000001"])
def test_explicit_bounded_fee_evidence_required(fee):
    with pytest.raises(PaperContractError):
        normalize_order(order(), cumulative_fee=fee)


@pytest.mark.parametrize("status,quantity,price,fee", [
    ("new", "0", None, "0"), ("accepted", "0", None, "0"),
    ("pending_new", "0", None, "0"), ("filled", "4", "100", "0.1"),
    ("canceled", "2", "100", "0.1"), ("expired", "0", None, "0"),
    ("rejected", "0", None, "0"),
])
def test_supported_state_shapes(status, quantity, price, fee):
    normalize_order(order(status=status, filled_qty=quantity, filled_avg_price=price), cumulative_fee=fee).validate()


def test_unknown_submission_recovered_then_duplicate_stale_cancel_and_fill_race(tmp_path):
    path = tmp_path / "orders.sqlite3"
    book, cid = prepared(path)
    raw = order(cid)
    assert reconcile_recording(book, bundle(raw))["ready"]
    report = normalize_order(raw, cumulative_fee="0.1")
    assert book.apply(normalize_trade_update(dict(event="partial_fill", order=raw), cumulative_fee="0.1")) == "DUPLICATE"
    assert book.snapshot()["cash"] == "799.9"
    assert book.claim_cancel(cid)
    canceled = order(cid, status="canceled", updated_at=LATER)
    book.apply(normalize_order(canceled, cumulative_fee="0.1"))
    assert book.apply(normalize_order(order(cid, updated_at="2025-02-03T14:59:59Z"), cumulative_fee="0.1")) == "STALE"
    filled = order(cid, status="filled", filled_qty="4", updated_at="2025-02-03T15:00:02Z")
    book.apply(normalize_order(filled, cumulative_fee="0.2"))
    assert book.snapshot()["cash"] == "599.8"
    assert book.snapshot()["positions"] == {"SPY": 4}
    book.close()
    with OfflineOrderBook(path, "paper-contract-test", 1000) as restarted:
        assert not admission(restarted)["review_ready"]
        final = bundle(filled)
        final.update(captured_at="2025-02-03T15:00:03Z", account={"currency": "USD", "cash": "599.8"},
                     positions=[dict(symbol="SPY", qty="4", side="long", asset_class="us_equity")],
                     cumulative_fees={"broker-1": "0.2"}, cumulative_notionals={"broker-1": "400"})
        assert reconcile_recording(restarted, final)["ready"]
        assert admission(restarted)["review_ready"]
        assert admission(restarted)["execution_enabled"] is False


def test_same_revision_conflict_halts(tmp_path):
    book, cid = prepared(tmp_path / "book.db")
    try:
        book.apply(normalize_order(order(cid), cumulative_fee="0.1"))
        with pytest.raises(ValueError):
            book.apply(normalize_order(order(cid), cumulative_fee="0.2"))
        assert not book.ready
        assert book.snapshot()["cash"] == "799.9"
    finally:
        book.close()


@pytest.mark.parametrize("change", [
    {"complete": False}, {"coherent": False}, {"endpoint": "https://api.alpaca.markets"},
    {"cumulative_fees": {}}, {"cumulative_fees": {"broker-1": "0.1", "extra": "0"}},
    {"captured_at": "2025-02-03T14:00:00Z"}, {"orders": [order(), order()]},
    {"positions": [dict(symbol="SPY", qty="-2", side="short", asset_class="us_equity")]},
])
def test_invalid_bundle_pauses_before_any_fill(tmp_path, change):
    book, cid = prepared(tmp_path / "book.db")
    try:
        result = reconcile_recording(book, dict(bundle(order(cid)), **change))
        assert not result["ready"]
        assert book.snapshot()["cash"] == "1000"
        assert book.order(cid)["filled_quantity"] == 0
    finally:
        book.close()


@pytest.mark.parametrize("change,issue", [
    ({"account": {"status": "ACTIVE"}}, "account_not_ready"),
    ({"clock": {"is_open": False}}, "market_not_open"),
    ({"asset": {"symbol": "QQQ"}}, "asset_not_ready"),
    ({"endpoint": "https://api.alpaca.markets"}, "paper_endpoint_required"),
    ({"now": "2025-02-03T15:00:07Z"}, "stale_or_invalid_evidence"),
    ({"now": STAMP}, "stale_or_invalid_evidence"),
])
def test_admission_requires_explicit_current_account_asset_clock(tmp_path, change, issue):
    book, cid = prepared(tmp_path / "book.db")
    try:
        assert reconcile_recording(book, bundle(order(cid)))["ready"]
        result = admission(book, **change)
        assert not result["review_ready"] and issue in result["issues"]
        assert not result["execution_enabled"]
    finally:
        book.close()


def test_unowned_order_and_cash_mismatch_pause(tmp_path):
    book, cid = prepared(tmp_path / "book.db")
    try:
        result = reconcile_recording(book, bundle(order()))
        assert not result["ready"] and "unowned_broker_order" in result["issues"]
        changed = bundle(order(cid))
        changed["account"]["cash"] = "799.8"
        assert "cash_mismatch" in reconcile_recording(book, changed)["issues"]
        assert not book.ready
    finally:
        book.close()


def test_stream_mismatch_and_gateway_have_no_side_effects(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network must not be used")
    import socket
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    with pytest.raises(PaperContractError, match="STATE_MISMATCH"):
        normalize_trade_update(dict(event="fill", order=order()), cumulative_fee="0.1")
    with pytest.raises(PaperContractError, match="UNSUPPORTED_TRADE_UPDATE"):
        normalize_trade_update(dict(event="trade_bust", order=order()), cumulative_fee="0.1")
    book, cid = prepared(tmp_path / "book.db")
    try:
        before = book.snapshot()
        gateway = DisabledPaperGateway()
        for operation in (gateway.submit, gateway.cancel):
            with pytest.raises(PaperContractError, match="PAPER_EXECUTION_DISABLED"):
                operation(cid)
        assert book.snapshot() == before
        assert not gateway.execution_enabled
    finally:
        book.close()


@pytest.mark.parametrize("notional", [None, True, "NaN", "-1", "0", "0.000000001"])
def test_execution_notional_is_required_independent_evidence(notional):
    with pytest.raises(PaperContractError):
        parse_order(order(), cumulative_fee="0.1", cumulative_notional=notional)


def test_rounded_average_is_not_used_as_cash_evidence():
    report = parse_order(order(filled_avg_price="100.12345678"),
                         cumulative_fee="0.1", cumulative_notional="200.24691357")
    assert report.filled_notional == Decimal("200.24691357")
    assert report.filled_notional != Decimal("100.12345678") * 2


def test_missing_lookup_does_not_clear_unknown_or_resubmit(tmp_path):
    book, cid = prepared(tmp_path / "book.db")
    try:
        empty = dict(endpoint=PAPER_ENDPOINT, complete=True, coherent=True, captured_at=LATER,
                     account={"currency": "USD", "cash": "1000"}, positions=[], orders=[], cumulative_fees={}, cumulative_notionals={})
        assert "order_not_found" in reconcile_recording(book, empty)["issues"]
        assert not book.claim_submission(cid)
        assert book.order(cid)["state"] == "UNKNOWN"
    finally:
        book.close()


def test_update_bridge_pauses_on_unsupported_then_requires_full_reconciliation(tmp_path):
    book, cid = prepared(tmp_path / "book.db")
    try:
        assert reconcile_recording(book, bundle(order(cid)))["ready"]
        assert apply_recorded_update(book, dict(event="trade_bust", order=order(cid)),
                                     cumulative_fee="0.1", cumulative_notional="200") == "PAUSED"
        assert not book.ready
        assert apply_recorded_update(book, dict(event="partial_fill", order=order(cid)),
                                     cumulative_fee="0.1", cumulative_notional="200") == "DUPLICATE"
        assert not book.ready
        assert reconcile_recording(book, bundle(order(cid)))["ready"]
    finally:
        book.close()


@pytest.mark.parametrize("change", [{"account": {"currency": "EUR", "cash": "799.9"}},
                                    {"cumulative_notionals": {}},
                                    {"cumulative_notionals": {"broker-1": None}}])
def test_missing_execution_evidence_or_foreign_currency_is_rejected(change):
    with pytest.raises(PaperContractError):
        recorded_snapshot(dict(bundle(order()), **change))


def test_unhashable_update_event_is_redacted():
    with pytest.raises(PaperContractError, match="UNSUPPORTED_TRADE_UPDATE"):
        parse_update(dict(event=[]), cumulative_fee="0", cumulative_notional="0")
