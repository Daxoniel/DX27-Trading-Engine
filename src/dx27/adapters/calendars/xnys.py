"""Materialize a bounded XNYS schedule; third-party rules stay outside Sentinel."""

from datetime import date
from importlib.metadata import version

from dx27.intelligence.sentinel.session_calendar import SessionCalendar, TradingSession


def load_xnys_calendar(start: date, end: date) -> SessionCalendar:
    import exchange_calendars

    if end < start:
        raise ValueError('calendar end precedes start')
    calendar = exchange_calendars.get_calendar('XNYS', start=start.isoformat(), end=end.isoformat())
    sessions = tuple(TradingSession(str(day.date()), calendar.session_open(day).to_pydatetime(),
                                   calendar.session_close(day).to_pydatetime())
                     for day in calendar.sessions)
    return SessionCalendar('exchange_calendars:XNYS', version('exchange-calendars'), start.isoformat(), end.isoformat(), sessions)
