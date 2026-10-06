from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from dx27.intelligence.sentinel import (
    ContextualActivation,
    DiscoveryEligibility,
    DiscoveryRejectionReason,
    KnownInterestSnapshot,
    Provenance,
    SubjectRef,
    UniverseMembership,
    UniverseTier,
)


NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def provenance(record: str, hour: int = 12) -> Provenance:
    return Provenance("fixture", NOW.replace(hour=hour), record)


def membership(**overrides) -> UniverseMembership:
    values = {
        "subject_id": "asset:stable-id",
        "tier": UniverseTier.CORE,
        "universe_config_id": "universe:v1",
        "membership_snapshot_id": "snapshot:2026-10-06",
        "membership_reason": "continuous monitoring",
        "provenance": (provenance("b", 13), provenance("a", 12)),
    }
    values.update(overrides)
    return UniverseMembership(**values)


def test_universe_tier_contains_exactly_four_canonical_values():
    assert [item.value for item in UniverseTier] == [
        "CORE", "CONTEXTUAL", "DISCOVERY", "EXCLUDED_NOISE"
    ]
    assert UniverseTier.__canonical_type_id__ == "sentinel.universe_tier"


def test_membership_is_immutable_and_deterministic():
    first = membership()
    assert first == membership()
    assert first.membership_id == membership().membership_id
    with pytest.raises(FrozenInstanceError):
        first.tier = UniverseTier.DISCOVERY


def test_membership_provenance_is_canonical_without_collapsing_distinct_records():
    original = membership()
    reversed_input = membership(provenance=tuple(reversed(original.provenance)))
    distinct_same_prefix = provenance("a", 13)
    retained = membership(provenance=(provenance("a", 12), distinct_same_prefix))

    assert original.provenance == reversed_input.provenance
    assert original.membership_id == reversed_input.membership_id
    assert len(retained.provenance) == 2


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("tier", UniverseTier.DISCOVERY),
        ("universe_config_id", "universe:v2"),
        ("membership_snapshot_id", "snapshot:later"),
    ],
)
def test_membership_semantic_changes_change_identity(change, value):
    assert membership().membership_id != membership(**{change: value}).membership_id


def test_membership_identity_is_subject_id_not_ticker_metadata():
    first = SubjectRef("asset:stable-id", "equity", symbol="OLD")
    renamed = SubjectRef("asset:stable-id", "equity", symbol="NEW")
    assert first.subject_id == renamed.subject_id == membership().subject_id
    assert "symbol" not in {item.name for item in fields(UniverseMembership)}


def test_contextual_activation_default_expiry_and_identity():
    activation = ContextualActivation("asset:a", "theme", NOW, NOW + timedelta(days=2))
    assert activation.ttl_days == 30
    assert activation.expires_at == NOW + timedelta(days=32)
    assert activation.activation_id == replace(activation).activation_id


def test_contextual_activation_validates_timestamps_and_ttl():
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="activated_at must be timezone-aware"):
        ContextualActivation("asset:a", "theme", naive, NOW)
    with pytest.raises(ValueError, match="latest_material_confirmation_at must be timezone-aware"):
        ContextualActivation("asset:a", "theme", NOW, naive)
    with pytest.raises(ValueError, match="cannot precede"):
        ContextualActivation("asset:a", "theme", NOW, NOW - timedelta(seconds=1))
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="positive"):
            ContextualActivation("asset:a", "theme", NOW, NOW, invalid)


def test_discovery_eligibility_invariants():
    reason = DiscoveryRejectionReason.ILLIQUID
    with pytest.raises(ValueError, match="cannot have"):
        DiscoveryEligibility("asset:a", "policy:v1", True, (reason,))
    with pytest.raises(ValueError, match="require"):
        DiscoveryEligibility("asset:a", "policy:v1", False, ())


def test_discovery_reasons_are_set_like_and_identity_is_order_independent():
    reasons = (DiscoveryRejectionReason.MICROCAP, DiscoveryRejectionReason.ILLIQUID)
    first = DiscoveryEligibility("asset:a", "policy:v1", False, reasons + reasons)
    second = DiscoveryEligibility("asset:a", "policy:v1", False, tuple(reversed(reasons)))
    assert first.rejection_reasons == second.rejection_reasons
    assert len(first.rejection_reasons) == 2
    assert first.eligibility_id == second.eligibility_id


def test_eligibility_contract_contains_no_production_thresholds():
    names = {item.name for item in fields(DiscoveryEligibility)}
    assert names == {
        "subject_id", "eligibility_config_id", "eligible", "rejection_reasons", "eligibility_id"
    }


def test_known_interest_snapshot_canonicalizes_duplicates_and_input_order():
    first = KnownInterestSnapshot(
        NOW,
        holding_subject_ids=("asset:b", "asset:a", "asset:a"),
        watchlist_subject_ids=("asset:d", "asset:c"),
    )
    second = KnownInterestSnapshot(
        NOW,
        holding_subject_ids=("asset:a", "asset:b"),
        watchlist_subject_ids=("asset:c", "asset:d"),
    )
    assert first.holding_subject_ids == ("asset:a", "asset:b")
    assert first == second
    assert first.snapshot_id == second.snapshot_id


def test_known_interest_is_descriptive_and_has_no_discovery_blocking_behavior():
    prohibited = {"should_scan", "allowed_for_discovery", "suppress_unknown", "is_discoverable", "discovery_filter"}
    assert not prohibited.intersection(dir(KnownInterestSnapshot))

