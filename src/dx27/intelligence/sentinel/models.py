"""Minimal immutable value objects shared by Sentinel stages."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DataStatus(str, Enum):
    """Availability of data required to make an observation."""

    __canonical_type_id__ = "sentinel.data_status"
    __canonical_type_version__ = "1"

    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    UNSUPPORTED_SESSION = "UNSUPPORTED_SESSION"
    SOURCE_ERROR = "SOURCE_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class SubjectRef:
    """Stable subject identity with optional human/provider-facing context.

    ``subject_id`` is the canonical identity.  ``symbol`` is descriptive and is
    deliberately optional because tickers can change or be reused.
    """

    __canonical_type_id__ = "sentinel.subject_ref"
    __canonical_type_version__ = "1"

    subject_id: str
    subject_kind: str
    symbol: str | None = None
    economic_role: str | None = None
    proxy_for: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.subject_id, "subject_id")
        _require_text(self.subject_kind, "subject_kind")
        for field_name in ("symbol", "economic_role", "proxy_for"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)


@dataclass(frozen=True)
class ObservationWindow:
    """Bounds of completed observations used to derive a fact."""

    __canonical_type_id__ = "sentinel.observation_window"
    __canonical_type_version__ = "1"

    start: datetime
    end: datetime
    timeframe: str
    completed: bool = True

    def __post_init__(self) -> None:
        _require_aware(self.start, "start")
        _require_aware(self.end, "end")
        _require_text(self.timeframe, "timeframe")
        if self.end < self.start:
            raise ValueError("observation window end cannot precede start")
        if self.completed is not True:
            raise ValueError("Sentinel observation windows must be completed")


@dataclass(frozen=True)
class Provenance:
    """Attribution for normalized input without provider-specific behavior."""

    __canonical_type_id__ = "sentinel.provenance"
    __canonical_type_version__ = "1"

    source_id: str
    observed_at: datetime
    source_record_id: str | None = None
    source_version: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_aware(self.observed_at, "observed_at")
        for field_name in ("source_record_id", "source_version"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)
