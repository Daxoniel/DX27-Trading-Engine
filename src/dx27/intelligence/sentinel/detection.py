"""Result contract for Sentinel detection evaluations."""

from dataclasses import dataclass

from dx27.intelligence.sentinel.events import DetectedEvent
from dx27.intelligence.sentinel.models import DataStatus


@dataclass(frozen=True)
class DetectionResult:
    """The availability and canonically ordered events from one evaluation."""

    data_status: DataStatus
    events: tuple[DetectedEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.data_status, DataStatus):
            raise TypeError("data_status must be a DataStatus")
        if not isinstance(self.events, tuple):
            raise TypeError("events must be a tuple")
        if any(not isinstance(event, DetectedEvent) for event in self.events):
            raise TypeError("events must contain only DetectedEvent values")
        if self.data_status is not DataStatus.AVAILABLE and self.events:
            raise ValueError("non-AVAILABLE detection results cannot contain events")
        object.__setattr__(self, "events", tuple(sorted(self.events, key=lambda event: event.event_id)))
