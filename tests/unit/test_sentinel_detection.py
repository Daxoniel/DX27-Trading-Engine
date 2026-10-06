from dataclasses import FrozenInstanceError, fields

import pytest

from dx27.intelligence.sentinel import DataStatus, DetectionResult
from test_activity_anomaly_detector import ActivityAnomalyDetector, config, inputs


def events():
    history, current = inputs()
    first = ActivityAnomalyDetector(config()).detect(history, current).events[0]
    second = ActivityAnomalyDetector(config(economic_category="OTHER_ACTIVITY")).detect(history, current).events[0]
    return first, second


def test_detection_result_is_immutable():
    result = DetectionResult(DataStatus.AVAILABLE)
    with pytest.raises(FrozenInstanceError):
        result.data_status = DataStatus.STALE


def test_available_zero_or_events_and_non_available_zero_are_valid():
    event, _ = events()
    assert DetectionResult(DataStatus.AVAILABLE).events == ()
    assert DetectionResult(DataStatus.AVAILABLE, (event,)).events == (event,)
    assert DetectionResult(DataStatus.SOURCE_ERROR).events == ()


def test_non_available_cannot_contain_events():
    event, _ = events()
    with pytest.raises(ValueError, match="cannot contain"):
        DetectionResult(DataStatus.INSUFFICIENT_HISTORY, (event,))


def test_events_are_ordered_by_id_without_collapsing_distinct_events():
    first, second = events()
    forward = DetectionResult(DataStatus.AVAILABLE, (first, second))
    reverse = DetectionResult(DataStatus.AVAILABLE, (second, first))
    assert forward == reverse
    assert len(forward.events) == 2
    assert [event.event_id for event in forward.events] == sorted((first.event_id, second.event_id))


def test_detection_result_has_no_priority_trading_or_gpt_fields():
    names = {item.name for item in fields(DetectionResult)}
    assert names == {"data_status", "events"}

