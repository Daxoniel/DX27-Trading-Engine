"""Immutable, explicitly bounded trading-session schedules supplied by adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import _require_aware, _require_text


def utc(value: datetime) -> datetime:
    _require_aware(value, 'timestamp')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradingSession:
    __canonical_type_id__ = 'sentinel.trading_session'
    __canonical_type_version__ = '1'

    session_id: str
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        day = date.fromisoformat(self.session_id)
        object.__setattr__(self, 'opens_at', utc(self.opens_at))
        object.__setattr__(self, 'closes_at', utc(self.closes_at))
        if self.opens_at >= self.closes_at:
            raise ValueError('session must close after opening')
        local = ZoneInfo('America/New_York')
        if self.opens_at.astimezone(local).date() != day or self.closes_at.astimezone(local).date() != day:
            raise ValueError('XNYS session label must match its local date')

    @property
    def decision_cutoff(self) -> datetime:
        return self.closes_at + timedelta(minutes=120)


@dataclass(frozen=True)
class SessionCalendar:
    """A complete schedule inside [valid_from, valid_through], never extrapolated.

    Missing dates inside the adapter-supplied bounds are closed days. Adapter
    source/version and the exact schedule enter its identity, independent of now.
    """
    __canonical_type_id__ = 'sentinel.session_calendar'
    __canonical_type_version__ = '1'

    source_id: str
    source_version: str
    valid_from: str
    valid_through: str
    sessions: tuple[TradingSession, ...]
    calendar_version: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.source_id, 'source_id')
        _require_text(self.source_version, 'source_version')
        date.fromisoformat(self.valid_from)
        date.fromisoformat(self.valid_through)
        if self.valid_through < self.valid_from or not isinstance(self.sessions, tuple) or not self.sessions:
            raise ValueError('calendar needs nonempty, bounded sessions')
        if any(not isinstance(s, TradingSession) for s in self.sessions):
            raise TypeError('typed session tuple required')
        sessions = tuple(sorted(self.sessions, key=lambda s: s.session_id))
        if len({s.session_id for s in sessions}) != len(sessions):
            raise ValueError('duplicate calendar session')
        if any(not self.valid_from <= s.session_id <= self.valid_through for s in sessions):
            raise ValueError('session outside calendar bounds')
        object.__setattr__(self, 'sessions', sessions)
        digest = stable_content_hash({'source_id': self.source_id, 'source_version': self.source_version,
                                      'valid_from': self.valid_from,
                                      'valid_through': self.valid_through, 'sessions': sessions})
        object.__setattr__(self, 'calendar_version', f'XNYS:{self.source_version}:{digest}')

    def get(self, session_id: str) -> TradingSession:
        day = date.fromisoformat(session_id)
        if not self.valid_from <= day.isoformat() <= self.valid_through:
            raise ValueError('date outside pinned calendar bounds')
        for session in self.sessions:
            if session.session_id == session_id:
                return session
        raise ValueError('unsupported non-trading session')

    def history(self, session_id: str, points: int) -> tuple[TradingSession, ...]:
        current = self.get(session_id)
        position = self.sessions.index(current)
        return self.sessions[max(0, position-points+1):position+1]

    def age(self, observation_session: str, current_session: str) -> int:
        return self.sessions.index(self.get(current_session)) - self.sessions.index(self.get(observation_session))

    def age_of_date(self, observation_day: str, current_session: str) -> int:
        """Completed XNYS sessions since a source date, including source holidays."""
        date.fromisoformat(observation_day)
        self.get(current_session)
        if not self.valid_from <= observation_day <= current_session:
            raise ValueError('observation date outside covered causal calendar')
        return sum(observation_day < s.session_id <= current_session for s in self.sessions)
