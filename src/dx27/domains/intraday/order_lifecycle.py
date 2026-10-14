"""Bounded whole-share, cumulative-report contracts for offline P2-H tests."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
import re

from dx27.core.models.trade_intent import TradeIntent, TradeSide


TERMINAL = frozenset({"filled", "canceled", "rejected", "expired"})
BROKER_STATES = TERMINAL | {"accepted", "partial"}
UNCERTAIN = frozenset({"SUBMITTING", "UNKNOWN", "CANCEL_PENDING", "CANCEL_UNKNOWN"})


def money(value, *, negative=False):
    if isinstance(value, bool):
        raise ValueError("invalid monetary value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid monetary value") from None
    if (not result.is_finite() or abs(result) > Decimal("1e15")
            or (not negative and result < 0) or result.as_tuple().exponent < -8):
        raise ValueError("money requires finite values with at most eight decimal places")
    return result


def money_text(value):
    return format(value.normalize(), "f") if value else "0"


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value):
        raise ValueError("invalid lifecycle identifier")
    return value


def symbol_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9./-]{0,15}", value):
        raise ValueError("invalid symbol")
    return value


def whole_quantity(value, *, positive=True):
    if isinstance(value, bool) or not isinstance(value, int) or not (1 if positive else 0) <= value <= 1_000_000_000:
        raise ValueError("quantity must be bounded whole shares")
    return value


@dataclass(frozen=True)
class OrderRequest:
    intent_id: str
    strategy_id: str
    symbol: str
    side: TradeSide
    quantity: int
    reservation_price: Decimal
    fee_budget: Decimal = Decimal("0")

    def __post_init__(self):
        identifier(self.intent_id)
        identifier(self.strategy_id)
        symbol_value(self.symbol)
        whole_quantity(self.quantity)
        object.__setattr__(self, "side", TradeSide(self.side))
        object.__setattr__(self, "reservation_price", money(self.reservation_price))
        object.__setattr__(self, "fee_budget", money(self.fee_budget))
        if self.reservation_price <= 0:
            raise ValueError("reservation price must be positive")
        money(self.reservation_price * self.quantity + self.fee_budget)

    @classmethod
    def from_intent(cls, intent: TradeIntent, intent_id, reservation_price, fee_budget=0):
        if (intent.notional is not None or intent.quantity is None or isinstance(intent.quantity, bool)
                or not isinstance(intent.quantity, (int, float)) or not isfinite(intent.quantity)
                or intent.quantity != int(intent.quantity)):
            raise ValueError("P2-H accepts explicit whole-share quantity intents only")
        return cls(intent_id, intent.strategy_id, intent.symbol, intent.side,
                   int(intent.quantity), reservation_price, fee_budget)

    def to_dict(self):
        result = asdict(self)
        result.update(side=self.side.value, reservation_price=money_text(self.reservation_price),
                      fee_budget=money_text(self.fee_budget))
        return result


@dataclass(frozen=True)
class OrderReport:
    event_id: str
    client_order_id: str
    broker_order_id: str
    revision: int
    symbol: str
    side: TradeSide
    quantity: int
    status: str
    filled_quantity: int = 0
    filled_notional: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")

    def __post_init__(self):
        for value in (self.event_id, self.client_order_id, self.broker_order_id):
            identifier(value)
        symbol_value(self.symbol)
        whole_quantity(self.quantity)
        whole_quantity(self.filled_quantity, positive=False)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("report revision must be a positive integer")
        object.__setattr__(self, "side", TradeSide(self.side))
        object.__setattr__(self, "filled_notional", money(self.filled_notional))
        object.__setattr__(self, "fee", money(self.fee))

    def validate(self):
        if self.status not in BROKER_STATES or self.filled_quantity > self.quantity:
            raise ValueError("invalid cumulative report status/quantity")
        if ((self.filled_quantity == 0) != (self.filled_notional == 0)
                or (self.filled_quantity == 0 and self.fee != 0)
                or (self.status == "accepted" and self.filled_quantity != 0)
                or (self.status == "partial" and not 0 < self.filled_quantity < self.quantity)
                or (self.status == "filled" and self.filled_quantity != self.quantity)
                or (self.status == "rejected" and (self.filled_quantity or self.fee))):
            raise ValueError("inconsistent cumulative report")

    def to_dict(self):
        result = asdict(self)
        result.update(side=self.side.value, filled_notional=money_text(self.filled_notional), fee=money_text(self.fee))
        return result


@dataclass(frozen=True)
class BrokerSnapshot:
    cash: Decimal
    positions: dict[str, int]
    orders: tuple[OrderReport, ...]
    complete: bool = True

    def __post_init__(self):
        if not isinstance(self.complete, bool):
            raise ValueError("snapshot completeness must be explicit")
        object.__setattr__(self, "cash", money(self.cash, negative=True))
        positions = {}
        for symbol, quantity in self.positions.items():
            symbol_value(symbol)
            if isinstance(quantity, bool) or not isinstance(quantity, int):
                raise ValueError("snapshot positions must be whole shares")
            if quantity:
                positions[symbol] = quantity
        object.__setattr__(self, "positions", positions)
