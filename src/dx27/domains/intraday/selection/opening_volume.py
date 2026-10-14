"""Compare completed opening volume with the preceding scheduled openings."""

from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite


@dataclass(frozen=True)
class OpeningVolumeConfig:
    lookback_sessions: int = 20
    minimum_rvol: float = 1.0

    def __post_init__(self):
        if (isinstance(self.lookback_sessions, bool) or not isinstance(self.lookback_sessions, int)
                or self.lookback_sessions < 1):
            raise ValueError("lookback_sessions must be a positive integer")
        if isinstance(self.minimum_rvol, bool) or not isfinite(self.minimum_rvol) or self.minimum_rvol <= 0:
            raise ValueError("minimum_rvol must be positive and finite")


class OpeningVolumeSelector:
    """One selection per symbol/session at open + 30 minutes.

    Missing and zero-volume minutes invalidate their opening. Invalid historical
    openings occupy their calendar slots: never skip backward to better data.
    Later minutes cannot affect a frozen selection or an opening's baseline.
    """

    opening_minutes = 30

    def __init__(self, symbols, config: OpeningVolumeConfig):
        self.symbols = tuple(sorted(set(symbols)))
        self.config = config
        self.history = {s: deque(maxlen=config.lookback_sessions) for s in self.symbols}
        self.rows = []
        self.session = None
        self.selected = set()

    def begin_session(self, session):
        if self.session is not None:
            if not self.finalized:
                raise ValueError("previous opening interval was not completed")
            if session.opens_at <= self.session.opens_at:
                raise ValueError("sessions must be processed in chronological order")
        self.session = session
        self.next_minute = session.opens_at
        self.cutoff = session.opens_at + timedelta(minutes=self.opening_minutes)
        if self.cutoff > session.closes_at:
            raise ValueError("session must include the full opening interval")
        self.volumes = {s: 0.0 for s in self.symbols}
        self.valid = {s: True for s in self.symbols}
        self.observed = {s: 0 for s in self.symbols}
        self.selected = set()
        self.finalized = False

    def observe_minute(self, at, bars):
        if self.session is None:
            raise ValueError("begin a session before observing minutes")
        if at >= self.cutoff:
            return
        if at != self.next_minute:
            raise ValueError("process every scheduled opening minute in order")
        for symbol in self.symbols:
            bar = bars.get(symbol)
            if bar is None:
                self.valid[symbol] = False
                continue
            if bar.symbol != symbol or bar.timestamp != at or bar.timeframe != "1m":
                raise ValueError("opening bars must match the symbol and scheduled minute")
            if not isfinite(bar.volume) or bar.volume <= 0:
                self.valid[symbol] = False
                continue
            self.volumes[symbol] += bar.volume
            if not isfinite(self.volumes[symbol]):
                raise ValueError("opening volume sum must be finite")
            self.observed[symbol] += 1
        self.next_minute += timedelta(minutes=1)
        if self.next_minute != self.cutoff:
            return
        for symbol in self.symbols:
            history = self.history[symbol]
            current = self.volumes[symbol] if self.valid[symbol] else None
            denominator = None
            if current is None:
                reason = "OPENING_INCOMPLETE"
            elif len(history) < self.config.lookback_sessions:
                reason = "INSUFFICIENT_HISTORY"
            elif any(value is None for _, value in history):
                reason = "HISTORY_INCOMPLETE"
            else:
                denominator = sum(value for _, value in history) / self.config.lookback_sessions
                if not isfinite(denominator) or denominator <= 0:
                    raise ValueError("opening volume baseline must be positive and finite")
                reason = "SELECTED" if current / denominator >= self.config.minimum_rvol else "BELOW_THRESHOLD"
            selected = reason == "SELECTED"
            if selected:
                self.selected.add(symbol)
            self.rows.append(dict(session=self.session.session_id, symbol=symbol,
                                  decision_at=self.cutoff.isoformat(), opening_minutes=self.opening_minutes,
                                  observed_minutes=self.observed[symbol], opening_volume=current,
                                  baseline_sessions=len(history), valid_baseline_sessions=sum(v is not None for _, v in history),
                                  baseline_start=history[0][0] if history else None,
                                  baseline_end=history[-1][0] if history else None,
                                  baseline_mean_volume=denominator,
                                  rvol=current / denominator if denominator is not None else None,
                                  minimum_rvol=self.config.minimum_rvol, selected=selected, reason=reason))
            history.append((self.session.session_id, current))
        self.finalized = True
