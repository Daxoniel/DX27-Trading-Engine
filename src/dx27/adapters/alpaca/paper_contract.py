"""Recorded Alpaca paper responses only; no HTTP client or execution transport.

Fees and executed notionals are independent cumulative evidence, never inferred
from an order's average price. A complete recorded bundle is an assertion by the fixture producer, not
proof that separately fetched live endpoints form an atomic account snapshot.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from dx27.domains.intraday.order_lifecycle import (
    BrokerSnapshot, OrderReport, identifier, money, symbol_value, whole_quantity,
)

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
_STATES = {"new": "accepted", "accepted": "accepted", "pending_new": "accepted",
           "partially_filled": "partial", "filled": "filled", "canceled": "canceled",
           "expired": "expired", "rejected": "rejected"}
_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z\Z")


class PaperContractError(ValueError):
    """Stable error codes; never contains vendor payloads or account identity."""


def timestamp_revision(value):
    """UTC nanosecond ordering shared by REST orders and trade-update orders."""
    match = _STAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise PaperContractError("INVALID_ORDER_TIMESTAMP")
    try:
        second = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        delta = second - datetime(1970, 1, 1, tzinfo=timezone.utc)
        result = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + int((match[2] or "").ljust(9, "0"))
        if result <= 0:
            raise ValueError
        return result
    except ValueError:
        raise PaperContractError("INVALID_ORDER_TIMESTAMP") from None


def _quantity(value, *, zero=False):
    # Alpaca quantities are decimal strings. Fractional shares remain unsupported.
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,10}(?:\.0{1,8})?", value):
        raise ValueError
    return whole_quantity(int(Decimal(value)), positive=not zero)


def normalize_order(order, *, cumulative_fee, cumulative_notional):
    """Normalize authoritative cumulative totals; unsupported states fail closed.

    Different normalized totals at the same updated_at produce different event
    IDs with the same revision, so the persistent book detects a revision conflict.
    """
    try:
        if not isinstance(order, dict):
            raise ValueError
        status = _STATES.get(order.get("status"))
        if status is None:
            raise PaperContractError("UNSUPPORTED_ORDER_STATE")
        if (order.get("asset_class") != "us_equity" or order.get("type") != "market"
                or order.get("time_in_force") != "day" or order.get("extended_hours") is not False
                or order.get("notional") is not None or order.get("order_class", "simple") != "simple"
                or order.get("legs") not in (None, [])):
            raise PaperContractError("UNSUPPORTED_ORDER_SHAPE")
        quantity, filled = _quantity(order["qty"]), _quantity(order["filled_qty"], zero=True)
        average = order.get("filled_avg_price")
        if filled:
            price = money(average)
            if price <= 0:
                raise ValueError
            notional = money(cumulative_notional)
            if notional <= 0:
                raise ValueError
        else:
            if average is not None:
                raise ValueError
            notional = money(cumulative_notional)
            if notional != 0:
                raise ValueError
        report = OrderReport(
            "pending", identifier(order["client_order_id"]), identifier(order["id"]),
            timestamp_revision(order["updated_at"]), symbol_value(order["symbol"]),
            order["side"], quantity, status, filled, notional, money(cumulative_fee))
        report.validate()
        body = report.to_dict()
        body.pop("event_id")
        digest = sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        body["event_id"] = "alpaca-paper-" + digest
        return OrderReport(**body)
    except PaperContractError:
        raise
    except (ValueError, KeyError, TypeError, InvalidOperation, OverflowError):
        raise PaperContractError("INVALID_ORDER_RESPONSE") from None


def normalize_trade_update(update, *, cumulative_fee, cumulative_notional):
    """Envelope events are notifications, not incremental fills or revisions."""
    if not isinstance(update, dict) or not isinstance(update.get("event"), str) or update["event"] not in {
        "new", "accepted", "pending_new", "partial_fill", "fill", "canceled", "expired", "rejected"
    }:
        raise PaperContractError("UNSUPPORTED_TRADE_UPDATE")
    report = normalize_order(update.get("order"), cumulative_fee=cumulative_fee,
                             cumulative_notional=cumulative_notional)
    expected = {"partial_fill": "partial", "fill": "filled", "new": "accepted",
                "pending_new": "accepted"}.get(update["event"], update["event"])
    if report.status != expected:
        raise PaperContractError("TRADE_UPDATE_STATE_MISMATCH")
    return report


def recorded_snapshot(bundle):
    """Strict, explicitly complete fixture bundle, including terminal own orders.

    Open-order lists alone are insufficient. Cost evidence must cover every
    returned order exactly. Unowned orders remain visible for book reconciliation.
    """
    try:
        if (not isinstance(bundle, dict) or bundle.get("endpoint") != PAPER_ENDPOINT
                or bundle.get("complete") is not True or bundle.get("coherent") is not True):
            raise PaperContractError("INCOMPLETE_RECORDED_SNAPSHOT")
        captured = timestamp_revision(bundle["captured_at"])
        account, positions, orders, fees, notionals = (bundle[k] for k in (
            "account", "positions", "orders", "cumulative_fees", "cumulative_notionals"))
        if (not isinstance(account, dict) or not isinstance(positions, list)
                or not isinstance(orders, list) or not isinstance(fees, dict)
                or not isinstance(notionals, dict)):
            raise ValueError
        if account.get("currency") != "USD" or len(positions) > 1000 or len(orders) > 10000:
            raise ValueError
        inventory = {}
        for position in positions:
            symbol = symbol_value(position["symbol"])
            if position.get("asset_class") != "us_equity" or position.get("side") != "long" or symbol in inventory:
                raise ValueError
            inventory[symbol] = _quantity(position["qty"])
        reports = tuple(normalize_order(order, cumulative_fee=fees[order["id"]],
                                        cumulative_notional=notionals[order["id"]]) for order in orders)
        ids = [r.broker_order_id for r in reports]
        if (len(set(ids)) != len(ids) or len({r.client_order_id for r in reports}) != len(reports)
                or set(ids) != set(fees) or set(ids) != set(notionals)
                or any(r.revision > captured for r in reports)):
            raise ValueError
        return BrokerSnapshot(money(account["cash"], negative=True), inventory, reports, complete=True)
    except PaperContractError:
        raise
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise PaperContractError("INVALID_RECORDED_SNAPSHOT") from None


class DisabledPaperGateway:
    """There is deliberately no transport dependency, enable switch or fallback."""

    execution_enabled = False

    def submit(self, *args, **kwargs):
        raise PaperContractError("PAPER_EXECUTION_DISABLED")

    def cancel(self, *args, **kwargs):
        raise PaperContractError("PAPER_EXECUTION_DISABLED")
