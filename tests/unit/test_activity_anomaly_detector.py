from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math
import statistics

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


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
SUBJECT = SubjectRef("asset:stable", "equity", "OLD")


def config(**changes) -> ActivityAnomalyConfig:
    values = dict(
        lookback=3,
        min_history=2,
        relative_volume_threshold=1.5,
        percentile_threshold=1.0,
        robust_z_threshold=None,
        economic_category="MARKET_ACTIVITY",
    )
    values.update(changes)
    return ActivityAnomalyConfig(**values)


def observation(
    day: int,
    volume: float = 10,
    *,
    status: DataStatus = DataStatus.AVAILABLE,
    timeframe: str = "1d",
    subject: SubjectRef = SUBJECT,
    provenance_record: str | None = None,
) -> ObservationEnvelope:
    end = NOW + timedelta(days=day)
    provenance = (Provenance("fixture", NOW, provenance_record or f"record:{day}"),)
    membership = UniverseMembership(
        subject.subject_id,
        UniverseTier.CONTEXTUAL,
        "universe:v1",
        "snapshot:v1",
        "fixture",
        provenance,
    )
    context = None
    if status is DataStatus.AVAILABLE:
        context = MarketContext(subject.symbol or "TEST", end, timeframe, 1, 1, 1, 1, volume)
    return ObservationEnvelope(
        subject,
        ObservationWindow(end - timedelta(days=1), end, timeframe),
        status,
        provenance,
        membership,
        context,
    )


def detector(**changes) -> ActivityAnomalyDetector:
    return ActivityAnomalyDetector(config(**changes))


def incomplete(item: ObservationEnvelope) -> ObservationEnvelope:
    window = object.__new__(ObservationWindow)
    object.__setattr__(window, "start", item.observation_window.start)
    object.__setattr__(window, "end", item.observation_window.end)
    object.__setattr__(window, "timeframe", item.observation_window.timeframe)
    object.__setattr__(window, "completed", False)
    object.__setattr__(item, "observation_window", window)
    return item


@pytest.mark.parametrize(
    "changes",
    [
        {"lookback": 1},
        {"min_history": 1},
        {"lookback": 2, "min_history": 3},
        {"relative_volume_threshold": 0},
        {"relative_volume_threshold": math.inf},
        {"percentile_threshold": 0},
        {"percentile_threshold": 1.1},
        {"robust_z_threshold": math.nan},
        {"economic_category": ""},
    ],
)
def test_config_validation(changes):
    with pytest.raises(ValueError):
        config(**changes)


def test_config_is_immutable_and_identity_is_deterministic():
    first = config()
    assert first == config()
    with pytest.raises(FrozenInstanceError):
        first.lookback = 4


def test_config_and_baseline_id_semantics():
    original = config()
    trigger_change = config(relative_volume_threshold=2.0)
    history_change = config(lookback=4)
    assert original.detector_config_id != trigger_change.detector_config_id
    assert original.baseline_id == trigger_change.baseline_id
    assert original.baseline_id != history_change.baseline_id
    assert original.baseline_id != config(min_history=3).baseline_id


def test_measurement_formula_is_deterministic_and_history_order_independent():
    history = (observation(-4, 1), observation(-3, 2), observation(-2, 4))
    current = observation(0, 8)
    first = detector().measure(history, current)
    second = detector().measure(tuple(reversed(history)), current)
    logs = [math.log1p(value) for value in (1, 2, 4)]
    log_median = statistics.median(logs)
    mad = statistics.median(abs(value - log_median) for value in logs)
    assert first == second
    assert first.sample_count == 3
    assert first.median_volume == 2
    assert first.historical_percentile == 1
    assert first.robust_z == pytest.approx(0.6744897501960817 * (math.log1p(8) - log_median) / mad)


def test_measurement_selects_latest_lookback():
    measurement = detector(lookback=2).measure(
        (observation(-5, 1000), observation(-3, 10), observation(-2, 20)), observation(0, 40)
    )
    assert measurement.sample_count == 2
    assert measurement.median_volume == 15


def test_status_results_and_normal_no_event():
    history = (observation(-3, 10), observation(-2, 20))
    assert detector().detect((history[0],), observation(0, 40)).data_status is DataStatus.INSUFFICIENT_HISTORY
    for status in (DataStatus.SOURCE_ERROR, DataStatus.UNAVAILABLE):
        result = detector().detect(history, observation(0, status=status))
        assert result.data_status is status and result.events == ()
    normal = detector().detect(history, observation(0, 15))
    assert normal.data_status is DataStatus.AVAILABLE and normal.events == ()


def test_elevated_event_has_expected_semantics_evidence_and_context():
    current = observation(0, 40)
    result = detector().detect((observation(-3, 10), observation(-2, 20)), current)
    event = result.events[0]
    assert event.event_type is EventType.ACTIVITY_ANOMALY
    assert event.direction is EventDirection.ELEVATED
    assert event.semantic_flags == (SemanticFlag.ANOMALOUS,)
    assert event.detector_id == "sentinel.activity_anomaly"
    assert event.observed_at == current.observation_window.end
    assert event.magnitude.metric == "relative_volume"
    assert {item.metric for item in event.evidence} == {
        "relative_volume", "historical_volume_percentile", "robust_volume_z"
    }
    assert event.universe_context.tier == UniverseTier.CONTEXTUAL.value
    assert event.provenance == current.provenance
    assert event.relevance_context.is_holding is False


def test_zero_mad_omits_robust_z_evidence_and_can_trigger_without_z_policy():
    event = detector().detect(
        (observation(-3, 10), observation(-2, 10)), observation(0, 20)
    ).events[0]
    assert event.magnitude.normalized_value is None
    assert "robust_volume_z" not in {item.metric for item in event.evidence}


@pytest.mark.parametrize(
    "future",
    [
        lambda: observation(1, 10),
        lambda: incomplete(observation(1, 10)),
        lambda: observation(1, 10, timeframe="1h"),
        lambda: observation(0, 10),
    ],
)
def test_all_available_future_or_overlapping_history_is_rejected(future):
    with pytest.raises(ValueError, match="overlap or follow"):
        detector().detect((future(),), observation(0, 20))


def test_prior_incomplete_and_non_daily_history_are_excluded():
    history = (
        observation(-4, 10),
        observation(-3, 20),
        incomplete(observation(-2, 1000)),
        observation(-1, 1000, timeframe="1h"),
    )
    measurement = detector().measure(history, observation(0, 40))
    assert measurement.sample_count == 2
    assert measurement.median_volume == 15


def test_duplicate_windows_and_subject_mismatch_are_rejected():
    same = observation(-2, 10)
    with pytest.raises(ValueError, match="duplicate"):
        detector().detect((same, replace(same)), observation(0, 30))
    other = SubjectRef("asset:other", "equity", "TEST")
    with pytest.raises(ValueError, match="subject_id"):
        detector().detect((observation(-2, subject=other),), observation(0, 30))


def test_future_unavailable_is_ignored_and_cannot_change_result():
    history = (observation(-3, 10), observation(-2, 20))
    current = observation(0, 40)
    unavailable_future = observation(2, status=DataStatus.UNAVAILABLE)
    assert detector().detect(history, current) == detector().detect(history + (unavailable_future,), current)


def test_history_order_preserves_event_and_lineage_identity():
    history = (observation(-3, 10), observation(-2, 20))
    current = observation(0, 40)
    first = detector().detect(history, current).events[0]
    second = detector().detect(tuple(reversed(history)), current).events[0]
    assert first.event_id == second.event_id
    assert first.deduplication_key == second.deduplication_key
    assert first.evidence_lineage == second.evidence_lineage


def test_trigger_change_changes_event_stream_but_not_baseline():
    history = (observation(-3, 10), observation(-2, 20))
    current = observation(0, 40)
    first = detector(relative_volume_threshold=1.5).detect(history, current).events[0]
    second = detector(relative_volume_threshold=2.0).detect(history, current).events[0]
    assert first.deduplication_key != second.deduplication_key
    assert first.baseline.baseline_id == second.baseline.baseline_id


def test_lineage_uses_windows_not_provenance_and_is_repeatable():
    history = (
        observation(-3, 10, provenance_record="same"),
        observation(-2, 20, provenance_record="same"),
    )
    event = detector().detect(history, observation(0, 40)).events[0]
    ids = event.evidence_lineage[0].source_observation_ids
    assert len(ids) == 3 and len(set(ids)) == 3
    assert event.evidence_lineage == detector().detect(history, observation(0, 40)).events[0].evidence_lineage


def test_ticker_rename_preserves_canonical_stream_and_lineage_semantics():
    renamed = SubjectRef(SUBJECT.subject_id, SUBJECT.subject_kind, "NEW")
    old_event = detector().detect(
        (observation(-3, 10), observation(-2, 20)), observation(0, 40)
    ).events[0]
    new_event = detector().detect(
        (observation(-3, 10, subject=renamed), observation(-2, 20, subject=renamed)),
        observation(0, 40, subject=renamed),
    ).events[0]
    assert old_event.deduplication_key == new_event.deduplication_key
    assert old_event.evidence_lineage == new_event.evidence_lineage


def test_comparison_window_covers_only_selected_baseline_range():
    history = (
        observation(-6, 999), observation(-4, 10), observation(-3, 15), observation(-2, 20)
    )
    event = detector().detect(history, observation(0, 40)).events[0]
    assert event.baseline.comparison_window.start == history[1].observation_window.start
    assert event.baseline.comparison_window.end == history[-1].observation_window.end
    assert {item.name for item in event.baseline.parameters} == {
        "lookback", "min_history", "transform", "center", "dispersion"
    }
