"""Recorded GET boundaries, stable observations and exact execution evidence."""

from copy import deepcopy
from decimal import Decimal

import pytest

from dx27.adapters.alpaca.paper_contract import PaperContractError, recorded_snapshot
from dx27.adapters.alpaca.paper_evidence import (
    RecordedPaperTransport, collect_recorded_evidence, reconcile_recorded_evidence,
)
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.domains.intraday.order_lifecycle import BrokerSnapshot, OrderRequest

AFTER = "2025-02-03T14:00:00Z"
THROUGH = "2025-02-03T15:00:09Z"
NOW = "2025-02-03T15:00:12Z"


def order(cid="client-1", **changes):
    raw = dict(id="broker-1", client_order_id=cid, symbol="SPY", side="buy", qty="4", filled_qty="2",
               filled_avg_price="100.12345678", status="partially_filled", created_at="2025-02-03T15:00:00Z",
               updated_at="2025-02-03T15:00:08Z", asset_class="us_equity", type="market", time_in_force="day",
               extended_hours=False, notional=None, order_class="simple", legs=None)
    return dict(raw, **changes)


def activities():
    rows = [dict(id="fill-1", order_id="broker-1", activity_type="FILL", type="fill", symbol="SPY", side="buy",
                 qty="1", price="100.12345678", cum_qty="1", transaction_time="2025-02-03T15:00:01Z"),
            dict(id="fill-2", order_id="broker-1", activity_type="FILL", type="fill", symbol="SPY", side="buy",
                 qty="1", price="100.12345679", cum_qty="2", transaction_time="2025-02-03T15:00:02Z"),
            dict(id="fee-1", order_id="broker-1", activity_type="FEE", currency="USD", net_amount="-0.1",
                 transaction_time="2025-02-03T15:00:03Z")]
    return rows


def cassette(raw=None, pages=None, *, observed="2025-02-03T15:00:10Z", page_size=2):
    raw = raw or order()
    pages = [activities()[:2], activities()[2:]] if pages is None else pages
    def entry(path, body, params=None):
        return dict(path=path, params=params or {}, body=deepcopy(body), status=200, observed_at=observed)
    one = [entry("/v2/account", dict(currency="USD", cash="799.65308643")),
           entry("/v2/positions", [dict(symbol="SPY", qty="2", side="long", asset_class="us_equity")]),
           entry("/v2/orders", [raw], dict(status="open", limit=500, direction="asc", nested=False)),
           entry("/v2/orders:by_client_order_id", raw, dict(client_order_id=raw["client_order_id"]))]
    token = None
    for page in pages:
        params = dict(activity_types="FILL,FEE,CFEE", after=AFTER, until=THROUGH,
                      direction="asc", page_size=page_size)
        if token is not None:
            params["page_token"] = token
        one.append(entry("/v2/account/activities", page, params))
        if page:
            token = page[-1]["id"]
    return one + deepcopy(one)


def transport(entries=None, **changes):
    return RecordedPaperTransport(entries if entries is not None else cassette(),
                                  **dict(history_after=AFTER, through=THROUGH, history_complete=True, **changes))


def collect(recording=None, **changes):
    return collect_recorded_evidence(recording or transport(),
                                     **dict(dict(client_order_ids=["client-1"], now=NOW, page_size=2), **changes))


def test_two_pass_pagination_exact_notional_and_fee_evidence_without_network(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError("network is forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    evidence = collect()
    result = recorded_snapshot(evidence["bundle"])
    assert result.orders[0].filled_notional == Decimal("200.24691357")
    assert result.orders[0].fee == Decimal("0.1")
    assert evidence["receipt"]["requests"] == 12
    assert evidence["receipt"]["activity_count"] == 3
    assert evidence["receipt"]["evidence_sha256"] == collect()["receipt"]["evidence_sha256"]
    assert not evidence["receipt"]["execution_enabled"] and not evidence["receipt"]["real_orders_sent"]


def test_overlap_is_deduplicated_and_exact_full_final_page_requires_empty_page():
    rows = activities()
    overlapping = cassette(pages=[rows[:2], rows[1:], []])
    assert collect(transport(overlapping))["receipt"]["activity_count"] == 3
    assert collect(transport(overlapping))["receipt"]["requests"] == 14


@pytest.mark.parametrize("mutation,code", [
    (lambda e: e[0].update(status=429), "QUERY_UNAVAILABLE"),
    (lambda e: e[3]["body"].update(client_order_id="wrong"), "LOOKUP_IDENTITY_CONFLICT"),
    (lambda e: e[2].update(body=[order()] * 500), "INVENTORY_TRUNCATED"),
    (lambda e: e[0].update(body="secret" * 50000), "RESPONSE_TOO_LARGE"),
    (lambda e: e[4]["body"][0].update(cum_qty="2"), "INCOMPLETE_EXECUTION_HISTORY"),
    (lambda e: e[4]["body"][1].update(order_id="unowned"), "UNOWNED_ACTIVITY_ORDER"),
    (lambda e: e[5]["body"][0].pop("order_id"), "INVALID_PAPER_EVIDENCE"),
    (lambda e: e[5]["body"][0].update(net_amount="0.1"), "UNSUPPORTED_FEE_ADJUSTMENT"),
    (lambda e: e[5]["body"][0].update(currency="EUR"), "UNSUPPORTED_FEE_CURRENCY"),
    (lambda e: e[4]["body"][0].update(type="trade_bust"), "INVALID_EXECUTION_ACTIVITY"),
    (lambda e: e[4]["body"][0].update(qty="0.5"), "INVALID_PAPER_EVIDENCE"),
    (lambda e: e[4]["body"][0].update(price="NaN"), "INVALID_PAPER_EVIDENCE"),
    (lambda e: e[4]["body"][0].update(symbol="QQQ"), "INVALID_EXECUTION_ACTIVITY"),
    (lambda e: e[4]["body"][0].update(side="sell"), "INVALID_EXECUTION_ACTIVITY"),
    (lambda e: e[4]["body"][1].update(transaction_time="2025-02-03T15:00:00Z"), "ORDER_REGRESSION"),
    (lambda e: e[4]["body"][0].update(transaction_time="2025-02-03T16:00:00Z"), "OUTSIDE_EVIDENCE_WINDOW"),
    (lambda e: e[1].update(observed_at="2025-02-03T15:00:09Z"), "CLOCK_REGRESSION"),
    (lambda e: e[6]["body"].update(cash="799"), "EVIDENCE_CHANGED"),
    (lambda e: e[3]["body"].update(updated_at="2025-02-03T15:00:10Z"), "ORDER_CHANGED_WITHIN_PASS"),
])
def test_incomplete_conflicting_and_unsupported_evidence_fails_redacted(mutation, code):
    entries = cassette()
    mutation(entries)
    with pytest.raises(PaperContractError, match=code) as exc:
        collect(transport(entries))
    assert "secret" not in str(exc.value)


def test_activity_conflict_and_cursor_stall():
    rows = activities()
    conflict = dict(rows[1], price="101")
    with pytest.raises(PaperContractError, match="ACTIVITY_ID_CONFLICT"):
        collect(transport(cassette(pages=[rows[:2], [conflict]])))
    with pytest.raises(PaperContractError, match="CURSOR_STALLED"):
        collect(transport(cassette(pages=[rows[:2], rows[:2]])))


def test_page_cap_and_incomplete_fill_history():
    with pytest.raises(PaperContractError, match="PAGE_LIMIT"):
        collect(max_pages=1)
    with pytest.raises(PaperContractError, match="INCOMPLETE_EXECUTION_HISTORY"):
        collect(transport(cassette(pages=[[activities()[0]]])))


def test_fees_require_observation_or_explicit_zero_attestation():
    rows = activities()[:2]
    recording = cassette(pages=[rows, []])
    with pytest.raises(PaperContractError, match="MISSING_FEE_EVIDENCE"):
        collect(transport(recording))
    assert collect(transport(recording), verified_zero_fee_orders=["broker-1"])["bundle"]["cumulative_fees"] == {"broker-1": "0"}
    with pytest.raises(PaperContractError, match="CONFLICTING_ZERO_FEE_EVIDENCE"):
        collect(verified_zero_fee_orders=["broker-1"])
    with pytest.raises(PaperContractError, match="UNOWNED_ZERO_FEE_EVIDENCE"):
        collect(verified_zero_fee_orders=["other"])


@pytest.mark.parametrize("changes", [{"page_size": True}, {"page_size": 0}, {"page_size": 101},
                                    {"max_pages": 0}, {"max_pages": 101},
                                    {"client_order_ids": ["client-1", "client-1"]},
                                    {"now": "2025-02-03T15:00:20Z"}, {"now": "2025-02-03T15:00:08Z"}])
def test_invalid_limits_and_stale_clock_fail_before_reads(changes):
    recording = transport()
    with pytest.raises(PaperContractError):
        collect(recording, **changes)
    assert recording.index == 0


def test_nonrecorded_transport_is_rejected_before_calls():
    class NetworkLike:
        def get(self, *args):
            raise AssertionError("must not be called")
    with pytest.raises(PaperContractError, match="RECORDED_PAPER_TRANSPORT_REQUIRED"):
        collect(NetworkLike())


def test_observation_window_and_history_coverage():
    entries = cassette(observed="2025-02-03T15:00:08Z")
    with pytest.raises(PaperContractError, match="OBSERVATION_WINDOW"):
        collect(transport(entries))
    raw = order(created_at=AFTER)
    with pytest.raises(PaperContractError, match="ORDER_OUTSIDE_EVIDENCE_WINDOW"):
        collect(transport(cassette(raw)))
    with pytest.raises(PaperContractError, match="HISTORY_NOT_ATTESTED"):
        RecordedPaperTransport(cassette(), history_after=AFTER, through=THROUGH, history_complete=False)


def test_collection_failure_does_not_apply_partial_account_evidence_and_never_retries(tmp_path):
    with OfflineOrderBook(tmp_path / "book.db", "recorded-evidence", 1000) as book:
        assert book.reconcile(BrokerSnapshot(Decimal(1000), {}, (), True))["ready"]
        request = OrderRequest("entry", "orb", "SPY", "buy", 4, Decimal(101), Decimal(1))
        cid = book.prepare(request)["client_order_id"]
        assert book.claim_submission(cid)
        book.uncertain(cid)
        entries = cassette(order(cid))
        entries[3]["status"] = 404
        recording = transport(entries)
        result = reconcile_recorded_evidence(book, recording, client_order_ids=[cid], now=NOW, page_size=2)
        assert not result["ready"] and recording.index == 4
        assert book.snapshot()["cash"] == "1000" and book.order(cid)["state"] == "UNKNOWN"
        assert not book.claim_submission(cid)
        fresh = transport(cassette(order(cid)))
        assert reconcile_recorded_evidence(book, fresh, client_order_ids=[cid], now=NOW, page_size=2)["ready"]
        assert book.snapshot()["cash"] == "799.65308643"
        assert book.snapshot()["positions"] == {"SPY": 2}


def test_terminal_order_is_looked_up_even_when_absent_from_open_inventory():
    entries = cassette(order(status="canceled"))
    entries[2]["body"] = []
    entries[8]["body"] = []
    assert collect(transport(entries))["bundle"]["orders"][0]["status"] == "canceled"


def test_order_version_change_between_passes_is_not_silently_accepted():
    entries = cassette()
    for index in (8, 9):
        entries[index]["body"] = ([dict(order(), updated_at="2025-02-03T15:00:08.1Z")]
                                   if index == 8 else dict(order(), updated_at="2025-02-03T15:00:08.1Z"))
    with pytest.raises(PaperContractError, match="EVIDENCE_CHANGED"):
        collect(transport(entries))


def test_future_observation_and_ignored_cassette_tail_are_rejected():
    with pytest.raises(PaperContractError, match="OBSERVATION_WINDOW"):
        collect(transport(cassette(observed="2025-02-03T15:00:13Z")))
    entries = cassette()
    entries.append(deepcopy(entries[-1]))
    with pytest.raises(PaperContractError, match="UNCONSUMED_PAPER_RECORDING"):
        collect(transport(entries))


def test_recording_has_no_retry_or_arbitrary_url_path():
    recording = transport()
    with pytest.raises(PaperContractError, match="GET_PATH_REJECTED"):
        recording.get("https://api.alpaca.markets/v2/orders")
    collect(recording)
    with pytest.raises(PaperContractError, match="ALREADY_USED"):
        collect(recording)


@pytest.mark.parametrize("change", [{"endpoint": "https://api.alpaca.markets"},
                                    {"history_after": THROUGH}, {"through": AFTER}])
def test_invalid_recorded_transport_metadata(change):
    values = dict(history_after=AFTER, through=THROUGH, history_complete=True)
    values.update(change)
    with pytest.raises(PaperContractError):
        RecordedPaperTransport(cassette(), **values)
