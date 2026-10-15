"""Sequential closed-minute research ledger; no file, network or broker access."""

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite

from dx27.core.models.market_context import MarketContext
from dx27.research.opening_direction import OpeningDirectionFixture, MINUTE

SEQUENCE_VERSION = "opening-direction-sequence-v1"


@dataclass
class ResearchResult:
    summary: dict
    daily: list
    fills: list
    trades: list
    equity: list
    decisions: list
    quality: list


class OpeningDirectionSequence:
    """Consume every minute in a pinned, ordered evaluation schedule.

    One position per day, no deposits, no daily capital resets. Input and output
    journals are retained for reproducibility; total memory is NOT constant.
    Checkpoint storage/durability and real-source registration belong to callers.
    """

    def __init__(self, sessions, profile):
        self.sessions = tuple(sessions)
        if not self.sessions or len(self.sessions) > 1000:
            raise ValueError("expected 1..1000 sessions")
        if any(a.session_id >= b.session_id or a.closes_at >= b.opens_at
               for a, b in zip(self.sessions, self.sessions[1:])):
            raise ValueError("session plan must be unique and chronological")
        self.profile = profile
        self._models = [OpeningDirectionFixture(self.sessions[0], profile)]
        self._current = self._models[0]
        self.initial_cash = self._current.initial_cash
        self.daily = []
        self.blocked = None

    @property
    def next_at(self):
        return self._current.next_at if self._current is not None and not self.blocked else None

    def on_closed_minute(self, at, bar, *, as_of):
        if self.next_at is None:
            raise ValueError("sequence finished or blocked")
        model = self._current
        model.on_closed_minute(at, bar, as_of=as_of)
        if model.next_at != model.session.closes_at:
            return
        r = model.report()
        valid = r["status"] == "COMPLETE_FIXTURE" and r["cash"] > 0 and isfinite(r["cash"])
        self.daily.append(dict(session=model.session.session_id,
                               starting_equity=model.initial_cash, ending_equity=r["equity"],
                               data_complete=r["data_valid"], open_positions=int(r["quantity"] != 0),
                               admissible=valid, closed_trades=r["closed_trades"],
                               net_pnl=r["equity"] - model.initial_cash,
                               daily_return=r["cash"] / model.initial_cash - 1 if valid else None))
        if not valid:
            self.blocked = "NONPOSITIVE_CAPITAL" if r["cash"] <= 0 else "INCOMPLETE_SESSION"
        elif len(self.daily) < len(self.sessions):
            self._current = OpeningDirectionFixture(self.sessions[len(self.daily)], self.profile,
                                                    starting_cash=r["cash"])
            self._models.append(self._current)
        else:
            self._current = None

    def checkpoint(self):
        return dict(version=SEQUENCE_VERSION, profile=self.profile,
                    sessions=[dict(session_id=s.session_id, opens_at=s.opens_at.isoformat(),
                                   closes_at=s.closes_at.isoformat()) for s in self.sessions],
                    journals=[m.checkpoint() for m in self._models])

    @classmethod
    def restore(cls, checkpoint, *, sessions, profile):
        model = cls(sessions, profile)
        expected = model.checkpoint()
        if not isinstance(checkpoint, dict) or set(checkpoint) != set(expected):
            raise ValueError("invalid sequence checkpoint")
        if any(checkpoint[k] != expected[k] for k in ("version", "profile", "sessions")):
            raise ValueError("sequence rule/profile/calendar mismatch")
        journals = checkpoint["journals"]
        if not isinstance(journals, list) or not 1 <= len(journals) <= len(model.sessions):
            raise ValueError("invalid journal count")
        for i, journal in enumerate(journals):
            current = model._current
            if current is None or model.blocked or current.session != model.sessions[i]:
                raise ValueError("journal after unfinished or blocked session")
            rebuilt = OpeningDirectionFixture.restore(journal, session=current.session, profile=profile,
                                                       starting_cash=current.initial_cash)
            if i < len(journals) - 1 and rebuilt.next_at != current.session.closes_at:
                raise ValueError("unfinished session before later journal")
            for tick in rebuilt.checkpoint()["ticks"]:
                bar = None if tick is None else MarketContext(**{
                    **tick, "timestamp": datetime.fromisoformat(tick["timestamp"])})
                model.on_closed_minute(model.next_at, bar, as_of=model.next_at + MINUTE)
        return model

    def result(self):
        fills, trades, equity, decisions, quality = [], [], [], [], []
        cash = self._models[-1].cash
        mark = self._models[-1].report()["equity"]
        for model in self._models:
            session = model.session.session_id
            fills.extend(dict(asdict(f), session=session,
                              cash_delta=(-1 if f.side == "buy" else 1) * f.quantity * f.price - f.commission)
                         for f in model.fills)
            equity.extend(dict(r, session=session) for r in model.equity)
            decisions.extend(dict(r, session=session) for r in model.decisions)
            if not model.data_valid:
                quality.append(dict(session=session, reason="MISSING_OR_ZERO_VOLUME"))
            if len(model.fills) == 2:
                r = model.report()
                trades.append(dict(session=session, net_pnl=r["realized_pnl"],
                                   gross_pnl=r["gross_pnl"], commission=r["commission"],
                                   spread_cost=r["spread_cost"], slippage_cost=r["slippage_cost"]))
        complete = self._current is None and not self.blocked
        summary = dict(status="COMPLETE_RESEARCH_SEQUENCE" if complete else
                       "BLOCKED_RESEARCH_SEQUENCE" if self.blocked else "INCOMPLETE_RESEARCH_SEQUENCE",
                       profile=self.profile, initial_cash=self.initial_cash, ending_cash=cash,
                       ending_equity=mark, net_pnl=cash-self.initial_cash if complete else None,
                       engineering_complete=complete, performance_admissible=False, execution_enabled=False,
                       effectiveness="NOT_EVALUATED", block_reason=self.blocked,
                       open_positions=int(self._models[-1].quantity != 0),
                       expected_sessions=len(self.sessions), completed_sessions=len(self.daily),
                       ambiguous_minutes=sum(m.ambiguous_minutes for m in self._models))
        return ResearchResult(summary, list(self.daily), fills, trades, equity, decisions, quality)
