"""One-session, closed-minute fixtures for the literature's opening-direction rule.

R0 is an idealized paper-rule reference, R1 a constrained long-only migration.
Neither profile is the production ORB bot, a broker, or an effectiveness study.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import floor, isclose, isfinite
from zoneinfo import ZoneInfo

from dx27.core.models.execution_costs import ExecutionCosts
from dx27.core.models.market_context import MarketContext
from dx27.core.models.trade_intent import TradeSide
from dx27.domains.intraday.market_data import validate_bar
from dx27.intelligence.sentinel.session_calendar import TradingSession

MINUTE = timedelta(minutes=1)
NY = ZoneInfo("America/New_York")
RULE_VERSION = "opening-direction-fixtures-v1"


@dataclass(frozen=True)
class ResearchFill:
    at: datetime
    side: str
    quantity: int
    reference: float
    price: float
    commission: float
    spread_cost: float
    slippage_cost: float
    reason: str


class OpeningDirectionFixture:
    """Bounded, deterministic minute-prefix model with replayable checkpoints.

    Call for every scheduled minute, explicitly supplying None for missing data.
    Entry size uses only prior-minute volume, never the entry minute's volume.
    One capped fill per side: no residual order, liquidity or borrow simulation.
    """

    def __init__(self, session: TradingSession, profile: str):
        if profile not in ("R0", "R1"):
            raise ValueError("profile must be R0 or R1")
        for at in (session.opens_at, session.closes_at):
            if at.second or at.microsecond:
                raise ValueError("session must be minute aligned")
        if session.opens_at.astimezone(NY).strftime("%H:%M") != "09:30":
            raise ValueError("expected regular-session 09:30 New York open")
        if not 15 * MINUTE <= session.closes_at - session.opens_at <= 390 * MINUTE:
            raise ValueError("unsupported session duration")
        self.session, self.profile = session, profile
        self.initial_cash = 25_000.0 if profile == "R0" else 100_000.0
        self.cash = self.initial_cash
        self.costs = (ExecutionCosts(0.0005, 0, 0, 0) if profile == "R0"
                      else ExecutionCosts())
        self.next_at = session.opens_at
        self.signal_at = session.opens_at + 5 * MINUTE
        self.entry_at = self.signal_at + (MINUTE if profile == "R1" else timedelta())
        self.flatten_at = session.closes_at - 5 * MINUTE
        self.direction = 0
        self.quantity = 0
        self.stop = self.target = self.entry_price = self.planned_risk = None
        self.realized_pnl = 0.0
        self.last_price = None
        self.prior_volume = 0.0
        self.opening = []
        self.fills = []
        self.decisions = []
        self.equity = []
        self.ambiguous_minutes = 0
        self.data_valid = True
        self._ticks = []

    def _decision(self, at, reason):
        self.decisions.append(dict(at=at.isoformat(), reason=reason))

    def on_closed_minute(self, at: datetime, bar: MarketContext | None, *, as_of: datetime):
        # Validate everything before changing state. Duplicate/reordered input is rejected.
        if at.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("aware timestamps required")
        if at != self.next_at or at >= self.session.closes_at or as_of != at + MINUTE:
            raise ValueError("expected next scheduled minute at its completion time")
        if bar is not None:
            validate_bar(bar)
            if bar.symbol != "QQQ" or bar.timestamp != at:
                raise ValueError("expected QQQ bar at the scheduled minute")
        usable = bar is not None and bar.volume > 0
        if not usable:
            self.data_valid = False
            self._decision(as_of, "MISSING_OR_ZERO_VOLUME")
        if at < self.signal_at:
            self.opening.append(bar if usable else None)
            if as_of == self.signal_at:
                self._freeze_signal()
        else:
            if at == self.entry_at:
                if not self.data_valid or not usable:
                    self._decision(at, "ENTRY_DATA_INVALID")
                elif self.direction:
                    self._enter(at, bar.open)
            if self.quantity and usable:
                self._manage(at, bar)
        if usable:
            self.last_price = bar.close
        equity = self.cash + self.quantity * (self.last_price or 0)
        self.equity.append(dict(at=as_of.isoformat(), equity=equity,
                                stale=not usable))
        self.prior_volume = bar.volume if usable else 0.0
        self._ticks.append(None if bar is None else {
            **asdict(bar), "timestamp": bar.timestamp.isoformat()})
        self.next_at = as_of

    def _freeze_signal(self):
        if len(self.opening) != 5 or any(bar is None for bar in self.opening):
            self._decision(self.signal_at, "OPENING_INCOMPLETE")
            return
        first, last = self.opening[0], self.opening[-1]
        high, low = max(b.high for b in self.opening), min(b.low for b in self.opening)
        if high <= low:
            self._decision(self.signal_at, "ZERO_RANGE")
            return
        direction = (last.close > first.open) - (last.close < first.open)
        if not direction:
            self._decision(self.signal_at, "DOJI")
            return
        if self.profile == "R1" and direction < 0:
            self._decision(self.signal_at, "SHORT_DISABLED")
            return
        self.direction = direction
        self.stop = low if direction > 0 else high
        self._decision(self.signal_at, "LONG" if direction > 0 else "SHORT")

    def _enter(self, at, reference):
        distance = self.direction * (reference - self.stop)
        if distance <= 0:
            self._decision(at, "NONPOSITIVE_R")
            return
        self.target = reference + self.direction * 10 * distance
        if not isfinite(self.target) or self.target <= 0:
            self._decision(at, "NONPOSITIVE_TARGET")
            return
        if self.profile == "R0":
            quantity = floor(min(self.initial_cash * .01 / distance,
                                 self.initial_cash * 4 / reference))
            self.planned_risk = quantity * distance + 2 * self.costs.commission(quantity)
        else:
            entry = self.costs.price(reference, TradeSide.BUY)
            stop_fill = self.costs.price(self.stop, TradeSide.SELL)
            upper = floor(min(self.cash / entry, self.initial_cash * .25 / entry,
                              self.prior_volume * .01))
            low, high = 0, max(0, upper)
            while low < high:
                q = (low + high + 1) // 2
                risk = q * (entry - stop_fill) + 2 * self.costs.commission(q)
                if risk <= self.initial_cash * .0025 and q * entry + self.costs.commission(q) <= self.cash:
                    low = q
                else:
                    high = q - 1
            quantity = low
            self.planned_risk = (quantity * (entry - stop_fill)
                                 + 2 * self.costs.commission(quantity)) if quantity else 0.0
        if quantity <= 0:
            self._decision(at, "ZERO_QUANTITY")
            return
        self._fill(at, quantity * self.direction, reference, "ENTRY")
        self.entry_price = self.fills[-1].price

    def _fill(self, at, signed_quantity, reference, reason):
        side = TradeSide.BUY if signed_quantity > 0 else TradeSide.SELL
        price = self.costs.price(reference, side)
        q = abs(signed_quantity)
        fee = self.costs.commission(q)
        self.cash -= signed_quantity * price + fee
        self.quantity += signed_quantity
        self.fills.append(ResearchFill(at, side.value, q, reference, price, fee,
                                      q * reference * self.costs.spread_bps / 20_000,
                                      q * reference * self.costs.slippage_bps / 10_000, reason))
        if reason != "ENTRY":
            self.realized_pnl = self.cash - self.initial_cash

    def _manage(self, at, bar):
        long = self.quantity > 0
        gap_stop = bar.open <= self.stop if long else bar.open >= self.stop
        gap_target = bar.open >= self.target if long else bar.open <= self.target
        hit_stop = bar.low <= self.stop if long else bar.high >= self.stop
        hit_target = bar.high >= self.target if long else bar.low <= self.target
        if gap_stop:
            reference, reason = bar.open, "GAP_STOP"
        elif gap_target:
            reference, reason = self.target, "GAP_TARGET_CAPPED"
        elif self.profile == "R1" and at >= self.flatten_at:
            reference, reason = bar.open, "SCHEDULED_FLATTEN"
        elif hit_stop:
            reference, reason = self.stop, "STOP"
            if hit_target:
                self.ambiguous_minutes += 1
                reason = "AMBIGUOUS_STOP_FIRST"
        elif hit_target:
            reference, reason = self.target, "TARGET"
        elif at + MINUTE == self.session.closes_at:
            reference, reason = bar.close, "SESSION_CLOSE_IDEALIZED"
        else:
            return
        # Open-based exits timestamp at the minute start; intrabar/end exits at completion.
        open_exit = reason in ("GAP_STOP", "GAP_TARGET_CAPPED", "SCHEDULED_FLATTEN")
        self._fill(at if open_exit else at + MINUTE, -self.quantity, reference, reason)

    def checkpoint(self):
        """JSON-safe bounded input journal; caller owns atomic storage, not this model."""
        return dict(version=RULE_VERSION, profile=self.profile,
                    session_id=self.session.session_id,
                    opens_at=self.session.opens_at.isoformat(),
                    closes_at=self.session.closes_at.isoformat(), ticks=deepcopy(self._ticks))

    @classmethod
    def restore(cls, checkpoint, *, session, profile):
        model = cls(session, profile)
        expected = model.checkpoint()
        if not isinstance(checkpoint, dict) or set(checkpoint) != set(expected):
            raise ValueError("invalid checkpoint schema")
        if any(checkpoint[k] != v for k, v in expected.items() if k != "ticks"):
            raise ValueError("checkpoint rule/profile/session mismatch")
        ticks = checkpoint["ticks"]
        maximum = int((session.closes_at - session.opens_at) / MINUTE)
        if not isinstance(ticks, list) or len(ticks) > maximum:
            raise ValueError("invalid checkpoint length")
        for tick in ticks:
            bar = None
            if tick is not None:
                if not isinstance(tick, dict) or set(tick) != set(MarketContext.__dataclass_fields__):
                    raise ValueError("invalid checkpoint bar")
                bar = MarketContext(**{**tick, "timestamp": datetime.fromisoformat(tick["timestamp"])})
            model.on_closed_minute(model.next_at, bar, as_of=model.next_at + MINUTE)
        return model

    def report(self):
        finished = self.next_at == self.session.closes_at
        complete = finished and self.data_valid and self.quantity == 0
        equity = self.cash + self.quantity * (self.last_price or 0)
        fees = sum(f.commission for f in self.fills)
        cash_from_fills = self.initial_cash - sum(
            (1 if f.side == TradeSide.BUY.value else -1) * f.quantity * f.price + f.commission
            for f in self.fills)
        if not isclose(self.cash, cash_from_fills, rel_tol=0, abs_tol=1e-7):
            raise RuntimeError("cash ledger mismatch")
        gross = (self.fills[0].quantity * self.direction *
                 (self.fills[-1].reference - self.fills[0].reference)) if len(self.fills) == 2 else None
        spread = sum(f.spread_cost for f in self.fills)
        slippage = sum(f.slippage_cost for f in self.fills)
        if gross is not None and not isclose(gross - fees - spread - slippage,
                                             self.realized_pnl, rel_tol=0, abs_tol=1e-7):
            raise RuntimeError("PnL ledger mismatch")
        return dict(status="COMPLETE_FIXTURE" if complete else "INCOMPLETE_FIXTURE",
                    rule_version=RULE_VERSION, profile=self.profile,
                    effectiveness="NOT_EVALUATED", execution_enabled=False,
                    cash=self.cash, equity=equity, quantity=self.quantity,
                    closed_trades=int(len(self.fills) == 2), realized_pnl=self.realized_pnl,
                    gross_pnl=gross, commission=fees, spread_cost=spread,
                    slippage_cost=slippage, planned_stop_risk=self.planned_risk,
                    ambiguous_minutes=self.ambiguous_minutes, data_valid=self.data_valid,
                    processed_minutes=len(self._ticks))
