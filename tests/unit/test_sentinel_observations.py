from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from dx27.core.models.market_context import MarketContext
from dx27.intelligence.sentinel import (
    DataStatus,
    ObservationCoverage,
    ObservationEnvelope,
    ObservationWindow,
    Provenance,
    SubjectRef,
    UniverseMembership,
    UniverseTier,
)


NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
SUBJECT = SubjectRef("asset:stable-id", "equity", symbol="TEST")


def source(record: str, minute: int = 0) -> Provenance:
    return Provenance("fixture", NOW.replace(minute=minute), record)


def membership(subject_id: str = SUBJECT.subject_id) -> UniverseMembership:
    return UniverseMembership(
        subject_id, UniverseTier.CORE, "universe:v1", "snapshot:v1", "important", (source("membership"),)
    )


def market_context() -> MarketContext:
    return MarketContext("TEST", NOW, "1d", 10.0, 12.0, 9.0, 11.0, 1000.0)


def envelope(**overrides) -> ObservationEnvelope:
    values = {
        "subject": SUBJECT,
        "observation_window": ObservationWindow(NOW - timedelta(days=1), NOW, "1d"),
        "data_status": DataStatus.AVAILABLE,
        "provenance": (source("b", 2), source("a", 1)),
        "universe_membership": membership(),
        "market_context": market_context(),
    }
    values.update(overrides)
    return ObservationEnvelope(**values)


def test_unknown_and_known_coverage_ratios():
    assert ObservationCoverage().coverage_ratio is None
    assert ObservationCoverage(4, 3).coverage_ratio == 0.75


@pytest.mark.parametrize("counts", [(0, 0), (-1, 0), (2, -1), (2, 3)])
def test_coverage_rejects_invalid_counts(counts):
    with pytest.raises(ValueError):
        ObservationCoverage(*counts)


@pytest.mark.parametrize("counts", [(2, None), (None, 1)])
def test_coverage_rejects_partially_known_counts(counts):
    with pytest.raises(ValueError, match="both"):
        ObservationCoverage(*counts)


def test_observation_envelope_is_immutable():
    observation = envelope()
    with pytest.raises(FrozenInstanceError):
        observation.data_status = DataStatus.STALE


def test_subject_membership_mismatch_and_empty_provenance_are_rejected():
    with pytest.raises(ValueError, match="subject_id must match"):
        envelope(universe_membership=membership("asset:other"))
    with pytest.raises(ValueError, match="must not be empty"):
        envelope(provenance=())


def test_provenance_order_is_canonical_and_distinct_records_remain():
    first = envelope()
    second = envelope(provenance=tuple(reversed(first.provenance)))
    distinct = envelope(provenance=(source("same", 1), source("same", 2)))
    assert first.provenance == second.provenance
    assert first == second
    assert len(distinct.provenance) == 2


def test_available_requires_existing_market_context():
    with pytest.raises(ValueError, match="require market_context"):
        envelope(market_context=None)
    assert isinstance(envelope().market_context, MarketContext)


@pytest.mark.parametrize("status", [DataStatus.UNAVAILABLE, DataStatus.SOURCE_ERROR])
def test_missing_statuses_accept_none_and_remain_explicit(status):
    observation = envelope(data_status=status, market_context=None)
    assert observation.data_status is status
    assert observation.market_context is None


def test_stale_may_carry_latest_existing_market_context():
    observation = envelope(data_status=DataStatus.STALE)
    assert observation.data_status is DataStatus.STALE
    assert type(observation.market_context) is MarketContext


def test_envelope_uses_existing_market_context_without_duplicating_ohlcv_or_trading_fields():
    names = {item.name for item in fields(ObservationEnvelope)}
    assert not {"open", "high", "low", "close", "volume"}.intersection(names)
    assert not {
        "bot_signal", "portfolio_target", "trade_intent", "execution_port",
        "side", "quantity", "position_size",
    }.intersection(names)


def test_observation_module_has_no_trading_or_execution_contract_dependencies():
    import dx27.intelligence.sentinel.observations as observations

    assert not {"BotSignal", "PortfolioTarget", "TradeIntent", "ExecutionPort"}.intersection(vars(observations))

