"""Bounded GET-only recorded paper evidence collection. No network transport.

The cassette producer explicitly attests historical coverage. Two identical
passes detect observed changes, but cannot prove atomic live broker snapshots.
"""

from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json

from dx27.adapters.alpaca.paper_contract import (
    PAPER_ENDPOINT, PaperContractError, _quantity, recorded_snapshot, timestamp_revision,
)
from dx27.domains.intraday.order_lifecycle import identifier, money, money_text

_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders",
                    "/v2/orders:by_client_order_id", "/v2/account/activities"})


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _require(condition, code):
    if not condition:
        raise PaperContractError(code)


class RecordedPaperTransport:
    """Finite expected-request cassette. Not a base class for live clients.

    Each entry contains path, params, status, observed_at and JSON body. The
    collector requires this exact type so no injected callable can send orders.
    """

    def __init__(self, entries, *, history_after, through, history_complete,
                 endpoint=PAPER_ENDPOINT):
        _require(endpoint == PAPER_ENDPOINT and history_complete is True, "PAPER_HISTORY_NOT_ATTESTED")
        _require(isinstance(entries, list) and 0 < len(entries) <= 512, "INVALID_PAPER_CASSETTE")
        _require(timestamp_revision(history_after) < timestamp_revision(through), "INVALID_HISTORY_WINDOW")
        self.entries = deepcopy(entries)
        self.history_after, self.through = history_after, through
        self.index, self.observations = 0, []

    def get(self, path, params=None):
        _require(path in _PATHS, "PAPER_GET_PATH_REJECTED")
        _require(self.index < len(self.entries), "PAPER_RECORDING_EXHAUSTED")
        entry = self.entries[self.index]
        _require(isinstance(entry, dict) and entry.get("path") == path
                 and entry.get("params", {}) == (params or {}), "PAPER_RECORDED_REQUEST_MISMATCH")
        self.index += 1
        _require(type(entry.get("status")) is int and entry["status"] == 200, "PAPER_QUERY_UNAVAILABLE")
        observed = timestamp_revision(entry["observed_at"])
        _require(not self.observations or observed >= self.observations[-1], "PAPER_OBSERVATION_CLOCK_REGRESSION")
        self.observations.append(observed)
        body = entry["body"]
        _require(len(_canonical(body).encode()) <= 262144, "PAPER_RESPONSE_TOO_LARGE")
        return deepcopy(body)


def _orders(transport, clients):
    opened = transport.get("/v2/orders", {"status": "open", "limit": 500, "direction": "asc", "nested": False})
    # Timestamp pagination of orders can lose equal-time boundary rows. Require
    # a short open-order page and separately resolve every known client identity.
    _require(isinstance(opened, list) and len(opened) < 500, "OPEN_ORDER_INVENTORY_TRUNCATED")
    result, client_ids = {}, {}
    looked_up = []
    for cid in clients:
        raw = transport.get("/v2/orders:by_client_order_id", {"client_order_id": cid})
        _require(isinstance(raw, dict) and raw.get("client_order_id") == cid, "ORDER_LOOKUP_IDENTITY_CONFLICT")
        looked_up.append(raw)
    for raw in opened + looked_up:
        _require(isinstance(raw, dict), "INVALID_ORDER_LOOKUP")
        bid, cid = identifier(raw["id"]), identifier(raw["client_order_id"])
        if bid in result:
            _require(_canonical(result[bid]) == _canonical(raw), "ORDER_CHANGED_WITHIN_PASS")
        _require(cid not in client_ids or client_ids[cid] == bid, "ORDER_LOOKUP_IDENTITY_CONFLICT")
        result[bid], client_ids[cid] = raw, bid
    _require(all(cid in client_ids for cid in clients), "ORDER_LOOKUP_IDENTITY_CONFLICT")
    _require(all(timestamp_revision(transport.history_after) < timestamp_revision(raw["created_at"])
                 and timestamp_revision(raw["updated_at"]) <= timestamp_revision(transport.through)
                 for raw in result.values()), "ORDER_OUTSIDE_EVIDENCE_WINDOW")
    return result


def _activities(transport, page_size, max_pages):
    token, seen_tokens, seen, result = None, set(), {}, []
    last_at = None
    for _ in range(max_pages):
        params = dict(activity_types="FILL,FEE,CFEE", after=transport.history_after,
                      until=transport.through, direction="asc", page_size=page_size)
        if token is not None:
            params["page_token"] = token
        rows = transport.get("/v2/account/activities", params)
        _require(isinstance(rows, list) and len(rows) <= page_size, "INVALID_ACTIVITY_PAGE")
        for row in rows:
            _require(isinstance(row, dict), "INVALID_ACTIVITY_ROW")
            event_id = identifier(row["id"])
            encoded = _canonical(row)
            if event_id in seen:
                _require(seen[event_id] == encoded, "ACTIVITY_ID_CONFLICT")
                continue
            at = timestamp_revision(row["transaction_time"])
            _require(timestamp_revision(transport.history_after) <= at <= timestamp_revision(transport.through),
                     "ACTIVITY_OUTSIDE_EVIDENCE_WINDOW")
            _require(last_at is None or at >= last_at, "ACTIVITY_ORDER_REGRESSION")
            last_at = at
            seen[event_id] = encoded
            result.append(row)
        if len(rows) < page_size:
            return result
        token = identifier(rows[-1]["id"])
        _require(token not in seen_tokens, "ACTIVITY_CURSOR_STALLED")
        seen_tokens.add(token)
    raise PaperContractError("ACTIVITY_PAGE_LIMIT")


def _costs(orders, activities, verified_zero_fee_orders):
    quantities = {bid: 0 for bid in orders}
    notionals, fees, fee_orders = dict.fromkeys(orders, Decimal(0)), dict.fromkeys(orders, Decimal(0)), set()
    for row in activities:
        bid = identifier(row["order_id"])
        _require(bid in orders, "UNOWNED_ACTIVITY_ORDER")
        raw = orders[bid]
        kind = row["activity_type"]
        if kind == "FILL":
            _require(row.get("type") == "fill" and row.get("symbol") == raw["symbol"]
                     and row.get("side") == raw["side"], "INVALID_EXECUTION_ACTIVITY")
            quantity, price = _quantity(row["qty"]), money(row["price"])
            _require(price > 0 and timestamp_revision(row["transaction_time"]) <= timestamp_revision(raw["updated_at"]),
                     "INVALID_EXECUTION_ACTIVITY")
            quantities[bid] += quantity
            _require(_quantity(row["cum_qty"], zero=True) == quantities[bid], "INCOMPLETE_EXECUTION_HISTORY")
            notionals[bid] = money(notionals[bid] + money(price * quantity))
        elif kind in {"FEE", "CFEE"}:
            _require(row.get("currency") == "USD", "UNSUPPORTED_FEE_CURRENCY")
            debit = money(row["net_amount"], negative=True)
            _require(debit < 0, "UNSUPPORTED_FEE_ADJUSTMENT")
            fees[bid] = money(fees[bid] - debit)
            fee_orders.add(bid)
        else:
            raise PaperContractError("UNSUPPORTED_ACTIVITY_TYPE")
    _require(set(verified_zero_fee_orders) <= set(orders), "UNOWNED_ZERO_FEE_EVIDENCE")
    _require(not (fee_orders & set(verified_zero_fee_orders)), "CONFLICTING_ZERO_FEE_EVIDENCE")
    for bid, raw in orders.items():
        _require(quantities[bid] == _quantity(raw["filled_qty"], zero=True), "INCOMPLETE_EXECUTION_HISTORY")
        _require(bid in fee_orders or bid in verified_zero_fee_orders, "MISSING_FEE_EVIDENCE")
    return ({bid: money_text(n) for bid, n in notionals.items()},
            {bid: money_text(fee) for bid, fee in fees.items()})


def _pass(transport, clients, page_size, max_pages, zero_fees):
    account = transport.get("/v2/account")
    positions = transport.get("/v2/positions")
    orders = _orders(transport, clients)
    activities = _activities(transport, page_size, max_pages)
    notionals, fees = _costs(orders, activities, zero_fees)
    bundle = dict(endpoint=PAPER_ENDPOINT, complete=True, coherent=True,
                  captured_at=transport.through, account=account, positions=positions,
                  orders=sorted(orders.values(), key=lambda raw: raw["id"]),
                  cumulative_notionals=notionals, cumulative_fees=fees)
    # H6 validates all cumulative totals/shape/positions before any ledger writes.
    recorded_snapshot(bundle)
    return bundle, activities


def collect_recorded_evidence(transport, *, client_order_ids, now, verified_zero_fee_orders=(),
                              page_size=100, max_pages=100):
    """Two complete equal recorded passes, no retries and no ledger mutation."""
    try:
        _require(type(transport) is RecordedPaperTransport, "RECORDED_PAPER_TRANSPORT_REQUIRED")
        _require(transport.index == 0 and not transport.observations, "PAPER_RECORDING_ALREADY_USED")
        _require(type(page_size) is int and 1 <= page_size <= 100
                 and type(max_pages) is int and 1 <= max_pages <= 100, "INVALID_EVIDENCE_LIMITS")
        _require(isinstance(client_order_ids, (list, tuple)) and len(client_order_ids) <= 100,
                 "INVALID_CLIENT_ORDER_INVENTORY")
        clients = tuple(identifier(cid) for cid in client_order_ids)
        _require(len(set(clients)) == len(clients), "DUPLICATE_CLIENT_ORDER_ID")
        _require(isinstance(verified_zero_fee_orders, (list, tuple, set, frozenset)), "INVALID_ZERO_FEE_EVIDENCE")
        zero_fees = frozenset(identifier(bid) for bid in verified_zero_fee_orders)
        current, through = timestamp_revision(now), timestamp_revision(transport.through)
        _require(0 <= current - through <= 5_000_000_000, "STALE_PAPER_EVIDENCE")
        start = len(transport.observations)
        first, first_activities = _pass(transport, clients, page_size, max_pages, zero_fees)
        second, second_activities = _pass(transport, clients, page_size, max_pages, zero_fees)
        observed = transport.observations[start:]
        _require(observed and through <= observed[0] <= observed[-1] <= current
                 and current - observed[0] <= 5_000_000_000, "INCOHERENT_OBSERVATION_WINDOW")
        _require(_canonical(first) == _canonical(second)
                 and _canonical(first_activities) == _canonical(second_activities), "PAPER_EVIDENCE_CHANGED")
        _require(transport.index == len(transport.entries), "UNCONSUMED_PAPER_RECORDING")
        return dict(bundle=second, receipt=dict(contract="P2-H7", mode="RECORDED_GET_ONLY",
                    requests=len(observed), activity_count=len(second_activities),
                    observation_start_ns=observed[0], observation_end_ns=observed[-1],
                    evidence_sha256=sha256(_canonical([second, second_activities, transport.history_after]).encode()).hexdigest(),
                    order_count=len(second["orders"]), history_coverage="PRODUCER_ATTESTED",
                    execution_enabled=False, real_orders_sent=False))
    except PaperContractError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError):
        raise PaperContractError("INVALID_PAPER_EVIDENCE") from None


def reconcile_recorded_evidence(book, transport, **kwargs):
    """Collection failures pause before applying any account execution evidence."""
    try:
        evidence = collect_recorded_evidence(transport, **kwargs)
    except PaperContractError:
        return book.pause_reconciliation("paper_evidence_unavailable")
    return book.reconcile(recorded_snapshot(evidence["bundle"]))
