from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from dx27.intelligence.sentinel import (
    BaselineParameter,
    DataStatus,
    DetectedEvent,
    EventBaseline,
    EventDirection,
    EventEvidence,
    EventLifecycle,
    EventMagnitude,
    EventRelationship,
    EventType,
    EvidenceLineage,
    IdentityKind,
    ObservationWindow,
    Provenance,
    RelevanceContext,
    SemanticFlag,
    SubjectRef,
    SubjectRole,
    UniverseContext,
    canonical_bytes,
    canonical_json,
    make_content_identity,
)


NOW = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
SPY = SubjectRef("us-equity:SPY", "ETF", symbol="SPY", economic_role="US_EQUITY_BROAD")
QQQ = SubjectRef("us-equity:QQQ", "ETF", symbol="QQQ", economic_role="US_EQUITY_GROWTH")


def window(end: datetime = NOW) -> ObservationWindow:
    return ObservationWindow(end - timedelta(days=20), end, "1d")


def lineage(*subjects: SubjectRef) -> EvidenceLineage:
    return EvidenceLineage(
        evidence_family="PRICE",
        source_observation_ids=("bar:2026-10-06", "bar:2026-10-05"),
        subject_ids=tuple(subject.subject_id for subject in subjects),
        baseline_id="baseline:trend-20d",
    )


def configuration(history: int = 20):
    return make_content_identity(
        IdentityKind.CONFIGURATION,
        "trend-detector",
        "1",
        {"history": history},
    )


def make_event(**overrides) -> DetectedEvent:
    subjects = overrides.pop("subjects", (SPY,))
    evidence_lineage = overrides.pop("evidence_lineage", (lineage(*subjects),))
    observed_at = overrides.pop("observed_at", NOW)
    observation_window = overrides.pop("observation_window", window(observed_at))
    evidence = overrides.pop(
        "evidence",
        (
            EventEvidence(
                metric="trend_slope",
                subject_id=subjects[0].subject_id,
                value=0.12,
                unit="slope",
                window=observation_window,
                data_status=DataStatus.AVAILABLE,
                lineage_id=evidence_lineage[0].lineage_id,
                reference_value=0.0,
            ),
        ),
    )
    values = {
        "schema_version": "1",
        "detector_id": "sentinel.trend_change",
        "detector_version": "1",
        "detector_config_id": configuration(),
        "event_type": EventType.TREND_CHANGE,
        "observed_at": observed_at,
        "observation_window": observation_window,
        "subjects": subjects,
        "economic_category": "US_EQUITY_BROAD",
        "direction": EventDirection.UP,
        "magnitude": EventMagnitude(
            metric="trend_slope",
            value=0.12,
            unit="slope",
            prior_value=-0.03,
            absolute_change=0.15,
        ),
        "baseline": EventBaseline(
            baseline_id="baseline:trend-20d",
            method="rolling_slope",
            comparison_window=observation_window,
            sample_count=20,
            reference_value=0.0,
            parameters=(BaselineParameter("history", 20),),
        ),
        "evidence": evidence,
        "evidence_lineage": evidence_lineage,
        "provenance": (Provenance("fixture", observed_at, "SPY:2026-10-06"),),
        "universe_context": UniverseContext("CORE", "universe:v1", "membership:2026-10-06"),
        "relevance_context": RelevanceContext(),
    }
    values.update(overrides)
    return DetectedEvent(**values)


def relationship() -> EventRelationship:
    return EventRelationship(
        relationship_kind="BENCHMARK_RELATIVE",
        subject_roles=(SubjectRole(QQQ.subject_id, "subject"), SubjectRole(SPY.subject_id, "benchmark")),
        expected_behavior="positive correlation",
        observed_behavior="diverging",
        comparison_window=window(),
        prior_strength=0.8,
    )


def test_event_type_vocabulary_contains_exactly_nine_frozen_values():
    assert [event_type.value for event_type in EventType] == [
        "PRICE_LEVEL_INTERACTION",
        "PRICE_GAP",
        "TREND_CHANGE",
        "ACTIVITY_ANOMALY",
        "VOLATILITY_CHANGE",
        "RELATIVE_STRENGTH_CHANGE",
        "PARTICIPATION_CHANGE",
        "RELATIONSHIP_CHANGE",
        "SERIES_STATE_CHANGE",
    ]


def test_event_models_are_immutable():
    event = make_event()

    for model, field_name, new_value in (
        (event, "economic_category", "CHANGED"),
        (event.magnitude, "value", 10.0),
        (event.baseline, "method", "changed"),
        (event.evidence[0], "value", 10.0),
        (event.evidence_lineage[0], "evidence_family", "changed"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(model, field_name, new_value)


def test_event_and_deduplication_identities_are_stable_and_distinct():
    first = make_event()
    second = make_event()

    assert first.event_id == second.event_id
    assert first.deduplication_key == second.deduplication_key
    assert first.event_id != first.deduplication_key


def test_semantically_identical_events_serialize_byte_identically():
    assert canonical_bytes(make_event()) == canonical_bytes(make_event())


def test_subject_order_is_canonical_for_event_identity():
    first_lineage = lineage(SPY, QQQ)
    first = make_event(
        event_type=EventType.RELATIONSHIP_CHANGE,
        direction=EventDirection.DIVERGING,
        subjects=(SPY, QQQ),
        evidence_lineage=(first_lineage,),
        evidence=(
            EventEvidence(
                "relative_return",
                SPY.subject_id,
                -0.03,
                "return",
                window(),
                DataStatus.AVAILABLE,
                first_lineage.lineage_id,
            ),
        ),
        relationship=relationship(),
    )
    second_lineage = lineage(QQQ, SPY)
    second = make_event(
        event_type=EventType.RELATIONSHIP_CHANGE,
        direction=EventDirection.DIVERGING,
        subjects=(QQQ, SPY),
        evidence_lineage=(second_lineage,),
        evidence=(
            EventEvidence(
                "relative_return",
                SPY.subject_id,
                -0.03,
                "return",
                window(),
                DataStatus.AVAILABLE,
                second_lineage.lineage_id,
            ),
        ),
        relationship=relationship(),
    )

    assert first.subjects == second.subjects
    assert first.event_id == second.event_id
    assert first.deduplication_key == second.deduplication_key


def test_occurrences_share_stream_key_but_not_event_id_when_facts_change():
    first = make_event()
    later_at = NOW + timedelta(days=1)
    later_window = window(later_at)
    later_lineage = EvidenceLineage(
        "PRICE",
        ("bar:2026-10-07", "bar:2026-10-06"),
        (SPY.subject_id,),
        "baseline:trend-20d",
    )
    second = make_event(
        observed_at=later_at,
        observation_window=later_window,
        evidence_lineage=(later_lineage,),
        evidence=(
            EventEvidence(
                "trend_slope",
                SPY.subject_id,
                0.18,
                "slope",
                later_window,
                DataStatus.AVAILABLE,
                later_lineage.lineage_id,
            ),
        ),
        magnitude=EventMagnitude("trend_slope", 0.18, "slope", prior_value=0.12),
        baseline=EventBaseline(
            "baseline:trend-20d", "rolling_slope", later_window, 20, reference_value=0.0
        ),
        provenance=(Provenance("fixture", later_at, "SPY:2026-10-07"),),
    )

    assert first.deduplication_key == second.deduplication_key
    assert first.event_id != second.event_id


def test_direction_reversal_preserves_semantic_stream_identity():
    upward = make_event(direction=EventDirection.UP)
    downward = make_event(direction=EventDirection.DOWN)

    assert upward.event_id != downward.event_id
    assert upward.deduplication_key == downward.deduplication_key


def test_current_baseline_measurement_does_not_define_semantic_stream():
    first = make_event()
    changed_measurement = make_event(
        baseline=EventBaseline(
            baseline_id="baseline:trend-20d",
            method="rolling_slope",
            comparison_window=window(),
            sample_count=20,
            reference_value=0.25,
            dispersion=0.08,
            parameters=(BaselineParameter("history", 20),),
        )
    )

    assert first.event_id != changed_measurement.event_id
    assert first.deduplication_key == changed_measurement.deduplication_key


def test_changed_baseline_definition_changes_semantic_stream_identity():
    first = make_event()
    changed_definition = make_event(
        baseline=EventBaseline(
            baseline_id="baseline:trend-60d",
            method="rolling_slope",
            comparison_window=window(),
            sample_count=60,
            reference_value=0.0,
            parameters=(BaselineParameter("history", 60),),
        )
    )

    assert first.event_id != changed_definition.event_id
    assert first.deduplication_key != changed_definition.deduplication_key


def test_detector_configuration_changes_occurrence_and_stream_identity():
    first = make_event(detector_config_id=configuration(20))
    second = make_event(detector_config_id=configuration(21))

    assert first.event_id != second.event_id
    assert first.deduplication_key != second.deduplication_key


def test_invalid_data_status_cannot_form_event_or_evidence():
    with pytest.raises(ValueError, match="AVAILABLE data"):
        make_event(data_status=DataStatus.STALE)

    with pytest.raises(ValueError, match="AVAILABLE data"):
        EventEvidence(
            "trend_slope",
            SPY.subject_id,
            0.12,
            "slope",
            window(),
            DataStatus.UNAVAILABLE,
            lineage(SPY).lineage_id,
        )


def test_proxy_evidence_requires_explicit_subject_identity_and_flag():
    proxy = SubjectRef(
        "us-equity:TLT", "ETF", symbol="TLT", economic_role="LONG_RATES", proxy_for="US30Y"
    )
    proxy_lineage = lineage(proxy)
    with pytest.raises(ValueError, match="PROXY_BASED"):
        make_event(subjects=(proxy,), evidence_lineage=(proxy_lineage,))

    with pytest.raises(ValueError, match="PROXY_BASED"):
        make_event(semantic_flags=(SemanticFlag.PROXY_BASED,))

    event = make_event(
        subjects=(proxy,),
        evidence_lineage=(proxy_lineage,),
        evidence=(
            EventEvidence(
                "price_trend",
                proxy.subject_id,
                -0.05,
                "return",
                window(),
                DataStatus.AVAILABLE,
                proxy_lineage.lineage_id,
            ),
        ),
        semantic_flags=(SemanticFlag.PROXY_BASED,),
    )
    assert event.subjects[0].proxy_for == "US30Y"


def test_relationship_change_requires_relationship_context():
    with pytest.raises(ValueError, match="requires relationship"):
        make_event(
            event_type=EventType.RELATIONSHIP_CHANGE,
            direction=EventDirection.DIVERGING,
        )


def test_relationship_roles_must_reference_event_subjects():
    with pytest.raises(ValueError, match="relationship roles"):
        make_event(
            event_type=EventType.RELATIONSHIP_CHANGE,
            direction=EventDirection.DIVERGING,
            relationship=relationship(),
        )


def test_direction_is_constrained_by_event_type():
    with pytest.raises(ValueError, match="invalid for PRICE_GAP"):
        make_event(event_type=EventType.PRICE_GAP, direction=EventDirection.STRENGTHENING)


def test_volatility_semantics_cannot_masquerade_as_series_state_change():
    with pytest.raises(ValueError, match="require VOLATILITY_CHANGE"):
        make_event(
            event_type=EventType.SERIES_STATE_CHANGE,
            economic_category="VOLATILITY",
            direction=EventDirection.UP,
        )


def test_evidence_lineage_is_explicit_canonical_and_deterministic():
    first = EvidenceLineage(
        "PRICE", ("bar:b", "bar:a", "bar:a"), (QQQ.subject_id, SPY.subject_id)
    )
    second = EvidenceLineage(
        "PRICE", ("bar:a", "bar:b"), (SPY.subject_id, QQQ.subject_id)
    )

    assert first == second
    assert first.lineage_id == second.lineage_id
    assert first.source_observation_ids == ("bar:a", "bar:b")
    assert first.subject_ids == tuple(sorted((SPY.subject_id, QQQ.subject_id)))


def test_actual_semantic_change_changes_event_id():
    first = make_event()
    changed = make_event(
        magnitude=EventMagnitude("trend_slope", 0.50, "slope", prior_value=-0.03)
    )

    assert first.event_id != changed.event_id
    assert first.deduplication_key == changed.deduplication_key


def test_event_identity_uses_stable_tags_not_python_module_paths():
    event = make_event()
    serialized = canonical_json(event)

    assert '"id":"sentinel.detected_event"' in serialized
    assert "dx27.intelligence.sentinel.events" not in serialized
    assert event.event_id == make_event().event_id


def test_detected_event_has_no_priority_or_trading_fields():
    field_names = {item.name for item in fields(DetectedEvent)}
    prohibited = {
        "priority",
        "trade_action",
        "side",
        "target_price",
        "stop",
        "quantity",
        "position_size",
        "execution_instruction",
        "portfolio_target",
        "bot_signal",
        "gpt_judgment",
    }

    assert field_names.isdisjoint(prohibited)
    assert [state.value for state in EventLifecycle] == [
        "NEW",
        "CONTINUING",
        "STRENGTHENED",
        "WEAKENED",
        "RESOLVED",
        "REVERSED",
    ]
