"""Explicitly synthetic normalized inputs for 6B-2H conformance, never live data."""

from datetime import date, timedelta
import math

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.market_state import MarketStateBuilder, SensorRegistry
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow, SubjectRef
from dx27.intelligence.sentinel.sensor_contracts import FeedBinding
from dx27.intelligence.sentinel.sensor_inputs import AvailabilityStamp, normalize_series_point


def synthetic_state_fixture(protocol: dict, sessions_count: int = 45) -> tuple:
    registry = SensorRegistry.from_protocol(protocol)
    calendar = load_xnys_calendar(date(2026, 1, 1), date(2026, 12, 31))
    if not 21 <= sessions_count <= len(calendar.sessions):
        raise ValueError('fixture requires 21 to 251 sessions inside its pinned calendar')
    sessions = calendar.sessions[:sessions_count]
    bindings = tuple(FeedBinding(f.feed_id, SubjectRef('fixture:' + f.feed_id, f.kind, symbol=f.feed_id.upper()),
                     'fixture', '1', 'percent' if f.feed_id == 'hy_oas' else f.unit, f.unit,
                     'fixture-only:validated-' + f.feed_id, sessions[0].opens_at - timedelta(days=1),
                     'XNYS' if f.kind == 'ETF' else 'fixture:validated-source-daily',
                     'TOTAL_RETURN_AS_AVAILABLE' if f.kind == 'ETF' else 'NOT_PRICE',
                     observation_label_policy='XNYS_SESSION' if f.kind == 'ETF' else 'LOCAL_DATE_OF_END') for f in registry.feeds)
    base = {'spy': 0.004, 'rsp': -0.001, 'qqq': 0.006, 'iwm': -0.002}
    points, raw_returns, prices = [], {}, {}
    for binding in bindings:
        price, daily, chain = 100.0, [], []
        for i, session in enumerate(sessions):
            if binding.price_basis == 'TOTAL_RETURN_AS_AVAILABLE':
                r = base.get(binding.feed_id, 0.001) + ((-1) ** i) * 0.003 + (i % 3) * 0.0002
                price *= math.exp(r)
                value = price
                daily.append(r)
                chain.append(price)
            else:
                value = {'vix': 18.0, 'hy_oas': 3.2, 'ust_2y': 2.5, 'ust_10y': 4.0,
                         'sofr': 4.1, 'effr': 4.0}[binding.feed_id]
            stamp = AvailabilityStamp(session.closes_at + timedelta(minutes=10), session.closes_at + timedelta(minutes=20),
                    session.session_id, '1', stable_content_hash({'feed': binding.feed_id, 'day': session.session_id, 'raw': value}))
            points.append(normalize_series_point(binding, ObservationWindow(session.opens_at, session.closes_at, '1d'),
                                                 DataStatus.AVAILABLE, value, stamp))
        raw_returns[binding.feed_id], prices[binding.feed_id] = daily, chain
    return registry, calendar, bindings, tuple(points), MarketStateBuilder(registry, calendar, bindings), raw_returns, prices
