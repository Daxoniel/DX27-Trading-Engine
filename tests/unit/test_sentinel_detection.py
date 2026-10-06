from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel import (
    ActivityAnomalyConfig,
    ActivityAnomalyDetector,
    DataStatus,
    DetectionResult,
    ObservationEnvelope,
    ObservationWindow,
    Provenance,
    SubjectRef,
    UniverseMembership,
    UniverseTier,
)


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
SUBJECT = SubjectRef("asset:stable", "equity", "TEST")


def observation(day: int, volume: float) -> ObservationEnvelope:
    end = NOW + timedelta(days=day)
    provenance = (Provenance("fixture", end, f"record:{day}"),)
    return ObservationEnvelope(
        SUBJECT,
        ObservationWindow(end - timedelta(days=1), end, "1d"),
        DataStatus.AVAILABLE,
        provenance,
        UniverseMembership(
            SUBJECT.subject_id,
            UniverseTier.CORE,
            "universe:v1",
            "snapshot:v1",
            "fixture",
            provenance,
        ),
        MarketContext("TEST", end, "1d", 1.0, 1.0, 1.0, 1.0, volume),
    )


def event(day: int, volume: float):
    detector = ActivityAnomalyDetector(ActivityAnomalyConfig(3, 2, 1.1, 0.5, None, "activity"))
    return detector.detect((observation(-3, 10), observation(-2, 20)), observation(day, volume)).events[0]


def test_result_is_immutable_and_available_can_have_zero_events():
    result = DetectionResult(DataStatus.AVAILABLE)
    assert result.events == ()
    with pytest.raises(FrozenInstanceError):
        result.data_status = DataStatus.UNAVAILABLE


def test_available_result_accepts_an_event():
    detected = event(0, 40)
    assert DetectionResult(DataStatus.AVAILABLE, (detected,)).events == (detected,)


@pytest.mark.parametrize("status", [DataStatus.UNAVAILABLE, DataStatus.SOURCE_ERROR])
def test_non_available_result_accepts_zero_events(status):
    assert DetectionResult(status).data_status is status


def test_non_available_result_rejects_events():
    with pytest.raises(ValueError, match="cannot contain"):
        DetectionResult(DataStatus.UNAVAILABLE, (event(0, 40),))


def test_event_order_is_canonical_and_distinct_events_remain_distinct():
    first = event(0, 40)
    second = event(1, 50)
    result = DetectionResult(DataStatus.AVAILABLE, (second, first))
    assert result.events == tuple(sorted((first, second), key=lambda item: item.event_id))
    assert len(result.events) == 2


def test_result_validates_status_events_and_has_no_policy_fields():
    with pytest.raises(TypeError, match="DataStatus"):
        DetectionResult("AVAILABLE")
    with pytest.raises(TypeError, match="DetectedEvent"):
        DetectionResult(DataStatus.AVAILABLE, (object(),))
    assert not {"priority", "trading", "gpt", "confidence"}.intersection(
        item.name.casefold() for item in fields(DetectionResult)
    )
