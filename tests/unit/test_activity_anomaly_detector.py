from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math

import pytest

from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel import (
    ActivityAnomalyConfig,
    ActivityAnomalyDetector,
    DataStatus,
    EventDirection,
    EventType,
    ObservationEnvelope,
    ObservationWindow,
    Provenance,
    SemanticFlag,
    SubjectRef,
    UniverseMembership,
    UniverseTier,
)


DAY = datetime(2026, 10, 20, tzinfo=timezone.utc)
SUBJECT = SubjectRef("asset:stable", "equity", symbol="OLD")


def config(**changes):
    values = dict(
        lookback=5,
        min_history=3,
        relative_volume_threshold=2.0,
        percentile_threshold=1.0,
        robust_z_threshold=None,
        economic_category="EQUITY_ACTIVITY",
    )
    values.update(changes)
    return ActivityAnomalyConfig(**values)


def observation(
    days_ago: int,
    volume: float,
    *,
    status: DataStatus = DataStatus.AVAILABLE,
    subject: SubjectRef = SUBJECT,
    timeframe: str = "1d",
) -> ObservationEnvelope:
    start = DAY - timedelta(days=days_ago)
    end = start + timedelta(days=1)
    provenance = (Provenance("fixture", end, f"record:{days_ago}:{volume}"),)
    membership = UniverseMembership(
        subject.subject_id,
        UniverseTier.CORE,
        "universe:v1",
        "snapshot:v1",
        "core subject",
        provenance,
    )
    context = None
    if status is DataStatus.AVAILABLE:
        context = MarketContext(subject.symbol or "UNKNOWN", end, timeframe, 10, 11, 9, 10, volume)
    return ObservationEnvelope(
        subject,
        ObservationWindow(start, end, timeframe),
        status,
        provenance,
        membership,
        context,
    )


def inputs(current_volume=500.0):
    history = tuple(observation(day, volume) for day, volume in zip(range(6, 1, -1), (90, 100, 110, 120, 130)))
    return history, observation(1, current_volume)


def test_config_validation_and_immutability():
    invalid = [
        {"lookback": 1}, {"min_history": 1}, {"min_history": 6},
        {"relative_volume_threshold": 0}, {"relative_volume_threshold": math.inf},
        {"percentile_threshold": 0}, {"percentile_threshold": 1.1},
        {"robust_z_threshold": 0}, {"robust_z_threshold": math.nan},
        {"economic_category": ""},
    ]
    for changes in invalid:
        with pytest.raises((TypeError, ValueError)):
            config(**changes)
    with pytest.raises(FrozenInstanceError):
        config().lookback = 10


def test_config_identity_and_baseline_identity_semantics():
    original = config()
    assert original.detector_config_id == config().detector_config_id
    for changed in (
        config(relative_volume_threshold=2.1),
        config(percentile_threshold=0.9),
        config(robust_z_threshold=1.0),
    ):
        assert changed.detector_config_id != original.detector_config_id
        assert changed.baseline_id == original.baseline_id
    for changed in (config(lookback=6), config(min_history=2)):
        assert changed.detector_config_id != original.detector_config_id
        assert changed.baseline_id != original.baseline_id


def test_measurement_formula_is_deterministic_and_history_order_independent():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    first = detector.measure(history, current)
    second = detector.measure(tuple(reversed(history)), current)
    assert first == second
    assert first.sample_count == 5
    assert first.median_volume == 110
    assert first.relative_volume == 500 / 110
    assert first.historical_percentile == 1
    assert first.robust_z is not None


def test_latest_lookback_is_used_for_measurement_and_event_baseline():
    history = tuple(observation(day, volume) for day, volume in zip(range(8, 1, -1), range(10, 80, 10)))
    current = observation(1, 500)
    detector = ActivityAnomalyDetector(config(lookback=3, min_history=2))
    measurement = detector.measure(history, current)
    event = detector.detect(history, current).events[0]
    assert measurement.sample_count == event.baseline.sample_count == 3
    assert measurement.median_volume == 60
    assert event.baseline.comparison_window.start == history[-3].observation_window.start
    assert event.baseline.comparison_window.end == history[-1].observation_window.end


def test_insufficient_and_current_failure_statuses_are_distinct():
    _, current = inputs()
    result = ActivityAnomalyDetector(config()).detect((observation(2, 100),), current)
    assert result.data_status is DataStatus.INSUFFICIENT_HISTORY and result.events == ()
    for status in (DataStatus.SOURCE_ERROR, DataStatus.UNAVAILABLE):
        unavailable = observation(1, 0, status=status)
        result = ActivityAnomalyDetector(config()).detect((), unavailable)
        assert result.data_status is status and result.events == ()


def test_normal_and_elevated_results_have_expected_semantics():
    history, normal = inputs(120)
    detector = ActivityAnomalyDetector(config())
    assert detector.detect(history, normal).data_status is DataStatus.AVAILABLE
    assert detector.detect(history, normal).events == ()

    _, elevated = inputs(500)
    event = detector.detect(history, elevated).events[0]
    assert event.event_type is EventType.ACTIVITY_ANOMALY
    assert event.direction is EventDirection.ELEVATED
    assert event.semantic_flags == (SemanticFlag.ANOMALOUS,)
    assert len(detector.detect(history, elevated).events) == 1
    assert {item.metric for item in event.evidence} == {
        "relative_volume", "historical_volume_percentile", "robust_volume_z"
    }
    assert not {"trade_action", "side", "bullish", "bearish"}.intersection(vars(event))


def test_zero_mad_has_no_robust_z_or_infinity_and_can_trigger_without_z_policy():
    history = tuple(observation(day, 100) for day in range(6, 1, -1))
    current = observation(1, 300)
    detector = ActivityAnomalyDetector(config())
    measurement = detector.measure(history, current)
    event = detector.detect(history, current).events[0]
    assert measurement.mad_log_volume == 0
    assert measurement.robust_z is None
    assert event.magnitude.normalized_value is None
    assert "robust_volume_z" not in {item.metric for item in event.evidence}


def test_subject_identity_uses_subject_id_not_symbol():
    history, current = inputs()
    with pytest.raises(ValueError, match="subject_id"):
        ActivityAnomalyDetector(config()).detect(history + (observation(2, 100, subject=SubjectRef("other", "equity")),), current)
    renamed = SubjectRef(SUBJECT.subject_id, SUBJECT.subject_kind, symbol="NEW")
    renamed_history = tuple(replace(item, subject=renamed) for item in history)
    assert ActivityAnomalyDetector(config()).detect(renamed_history, current).events


def test_future_overlap_and_duplicate_windows_are_rejected():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    future = observation(0, 100)
    overlapping = replace(history[0], observation_window=ObservationWindow(current.observation_window.start, current.observation_window.end, "1d"))
    for invalid in (history + (future,), history + (overlapping,), history + (history[0],)):
        with pytest.raises(ValueError):
            detector.detect(invalid, current)


def test_available_future_is_rejected_before_completeness_or_timeframe_filtering():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    future_incomplete = observation(0, 100)
    object.__setattr__(future_incomplete.observation_window, "completed", False)
    future_non_daily = observation(0, 100, timeframe="1h")

    for future in (future_incomplete, future_non_daily):
        with pytest.raises(ValueError, match="precede"):
            detector.detect(history + (future,), current)


def test_incomplete_and_non_daily_scope_behavior():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    incomplete_current = replace(current, observation_window=replace(current.observation_window))
    object.__setattr__(incomplete_current.observation_window, "completed", False)
    with pytest.raises(ValueError, match="completed"):
        detector.detect(history, incomplete_current)
    with pytest.raises(ValueError, match="daily"):
        detector.detect(history, observation(1, 500, timeframe="1h"))

    incomplete_history = replace(
        history[0], observation_window=replace(history[0].observation_window)
    )
    object.__setattr__(incomplete_history.observation_window, "completed", False)
    non_daily = observation(7, 100, timeframe="1h")
    selected = detector.measure(history[1:] + (incomplete_history, non_daily), current)
    assert selected.sample_count == 4


def test_prior_incomplete_and_non_daily_history_are_excluded_not_rejected():
    history, current = inputs()
    incomplete = replace(
        history[0], observation_window=replace(history[0].observation_window)
    )
    object.__setattr__(incomplete.observation_window, "completed", False)
    non_daily = observation(7, 100, timeframe="1h")

    measurement = ActivityAnomalyDetector(config()).measure(
        history[1:] + (incomplete, non_daily), current
    )
    assert measurement.sample_count == 4


@pytest.mark.parametrize("volume", [-1, math.inf, math.nan])
def test_invalid_used_volume_is_rejected(volume):
    history, current = inputs()
    bad = replace(history[0], market_context=replace(history[0].market_context, volume=volume))
    with pytest.raises(ValueError, match="volume"):
        ActivityAnomalyDetector(config()).detect((bad,) + history[1:], current)


def test_future_data_cannot_change_prior_result_and_reversed_history_is_identical():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    original = detector.detect(history, current)
    assert detector.detect(tuple(reversed(history)), current) == original
    assert detector.detect(tuple(reversed(history)), current).events[0].event_id == original.events[0].event_id
    assert detector.detect(tuple(reversed(history)), current).events[0].deduplication_key == original.events[0].deduplication_key
    assert detector.detect(history, current) == original
    with pytest.raises(ValueError, match="precede"):
        detector.detect(history + (observation(0, 200),), current)


def test_config_change_changes_event_stream_while_baseline_remains_same():
    history, current = inputs()
    first = ActivityAnomalyDetector(config(relative_volume_threshold=2.0)).detect(history, current).events[0]
    second_config = config(relative_volume_threshold=2.1)
    second = ActivityAnomalyDetector(second_config).detect(history, current).events[0]
    assert first.baseline.baseline_id == second.baseline.baseline_id
    assert first.deduplication_key != second.deduplication_key


def test_lineage_universe_and_current_provenance_are_deterministic():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    event = detector.detect(history, current).events[0]
    repeated = detector.detect(tuple(reversed(history)), current).events[0]
    lineage = event.evidence_lineage[0]
    assert lineage.subject_ids == (current.subject.subject_id,)
    assert lineage.baseline_id == detector.config.baseline_id
    assert lineage.source_observation_ids == repeated.evidence_lineage[0].source_observation_ids
    assert event.universe_context.tier == current.universe_membership.tier.value
    assert event.universe_context.universe_config_id == current.universe_membership.universe_config_id
    assert event.universe_context.membership_snapshot_id == current.universe_membership.membership_snapshot_id
    assert event.provenance == current.provenance


def test_lineage_distinguishes_windows_with_identical_provenance():
    history, current = inputs()
    shared = (Provenance("shared", DAY, "same-record"),)
    same_provenance_history = tuple(replace(item, provenance=shared) for item in history)
    same_provenance_current = replace(current, provenance=shared)
    detector = ActivityAnomalyDetector(config())

    first = detector.detect(same_provenance_history, same_provenance_current).events[0]
    repeated = detector.detect(same_provenance_history, same_provenance_current).events[0]
    reversed_event = detector.detect(
        tuple(reversed(same_provenance_history)), same_provenance_current
    ).events[0]
    source_ids = first.evidence_lineage[0].source_observation_ids

    assert len(source_ids) == len(history) + 1
    assert len(set(source_ids)) == len(source_ids)
    assert first.evidence_lineage[0].lineage_id == repeated.evidence_lineage[0].lineage_id
    assert first.evidence_lineage == reversed_event.evidence_lineage
    assert first.event_id == reversed_event.event_id


def test_lineage_observation_identity_ignores_ticker_metadata():
    history, current = inputs()
    detector = ActivityAnomalyDetector(config())
    original = detector.detect(history, current).events[0]
    renamed = SubjectRef(SUBJECT.subject_id, SUBJECT.subject_kind, symbol="NEW")
    renamed_history = tuple(replace(item, subject=renamed) for item in history)
    renamed_current = replace(current, subject=renamed)
    renamed_event = detector.detect(renamed_history, renamed_current).events[0]

    assert (
        original.evidence_lineage[0].source_observation_ids
        == renamed_event.evidence_lineage[0].source_observation_ids
    )
