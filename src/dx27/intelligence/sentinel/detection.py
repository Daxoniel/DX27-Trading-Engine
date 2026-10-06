"""Result contract for one deterministic Sentinel detection evaluation."""

from dataclasses import dataclass

from dx27.intelligence.sentinel.events import DetectedEvent
from dx27.intelligence.sentinel.models import DataStatus


@dataclass(frozen=True)
class DetectionResult:
    """Distinguish a successful no-event evaluation from unavailable data."""

    __canonical_type_id__ = "sentinel.detection_result"
    __canonical_type_version__ = "1"

    data_status: DataStatus
    events: tuple[DetectedEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.data_status, DataStatus):
            raise TypeError("data_status must be a DataStatus")
        if any(not isinstance(event, DetectedEvent) for event in self.events):
            raise TypeError("events must contain DetectedEvent values")
        if self.data_status is not DataStatus.AVAILABLE and self.events:
            raise ValueError("non-AVAILABLE detection results cannot contain events")
        object.__setattr__(self, "events", tuple(sorted(self.events, key=lambda event: event.event_id)))
