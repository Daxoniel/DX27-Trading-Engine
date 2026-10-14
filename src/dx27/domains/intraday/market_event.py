"""Provider-neutral closed-minute deliveries and reconnect control messages."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import re

from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.market_data import validate_bar


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("event clocks require aware timestamps")


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    source: str
    connection: str
    sequence: int
    kind: str
    available_at: datetime
    received_at: datetime
    bar: MarketContext | None = None
    revision: int = 0
    through: datetime | None = None

    def __post_init__(self):
        for name in ("event_id", "source", "connection"):
            if not isinstance(getattr(self, name), str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", getattr(self, name)):
                raise ValueError("invalid event identifier")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or not 1 <= self.sequence <= 1_000_000_000:
            raise ValueError("invalid delivery sequence")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or not 0 <= self.revision <= 1_000_000_000:
            raise ValueError("invalid bar revision")
        _timestamp(self.available_at)
        _timestamp(self.received_at)
        if self.received_at < self.available_at:
            raise ValueError("delivery precedes declared availability")
        if self.kind == "BAR":
            if not isinstance(self.bar, MarketContext) or self.revision < 1 or self.through is not None:
                raise ValueError("invalid closed-bar envelope")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in
                   (self.bar.open, self.bar.high, self.bar.low, self.bar.close, self.bar.volume)):
                raise ValueError("invalid event OHLCV numeric types")
            validate_bar(self.bar)
            if self.available_at < self.bar.timestamp + timedelta(minutes=1):
                raise ValueError("closed bar available before its interval ends")
        elif self.kind in {"CONNECT", "DISCONNECT", "SYNC"}:
            if self.bar is not None or self.revision != 0:
                raise ValueError("control message contains bar data")
            if self.kind == "SYNC":
                _timestamp(self.through)
                if self.through.second or self.through.microsecond or self.through > self.received_at:
                    raise ValueError("invalid synchronization boundary")
            elif self.through is not None:
                raise ValueError("unexpected synchronization boundary")
        else:
            raise ValueError("unsupported market event")
        for name in ("available_at", "received_at", "through"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, value.astimezone(timezone.utc))
        if self.bar is not None:
            object.__setattr__(self, "bar", replace(self.bar, timestamp=self.bar.timestamp.astimezone(timezone.utc)))
