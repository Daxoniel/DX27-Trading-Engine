"""Immutable universe contracts for Sentinel observation scope."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from dx27.intelligence.sentinel.identity import stable_content_hash
from dx27.intelligence.sentinel.models import Provenance


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _canonical_provenance(items: tuple[Provenance, ...]) -> tuple[Provenance, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.source_id,
                item.source_record_id or "",
                stable_content_hash(item),
            ),
        )
    )


class UniverseTier(str, Enum):
    """Canonical observation scope assigned to a universe subject."""

    __canonical_type_id__ = "sentinel.universe_tier"
    __canonical_type_version__ = "1"

    CORE = "CORE"
    CONTEXTUAL = "CONTEXTUAL"
    DISCOVERY = "DISCOVERY"
    EXCLUDED_NOISE = "EXCLUDED_NOISE"


@dataclass(frozen=True)
class UniverseMembership:
    """One subject's tier in a configured universe membership snapshot."""

    __canonical_type_id__ = "sentinel.universe_membership"
    __canonical_type_version__ = "1"

    subject_id: str
    tier: UniverseTier
    universe_config_id: str
    membership_snapshot_id: str
    membership_reason: str
    provenance: tuple[Provenance, ...]
    membership_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.subject_id, "subject_id")
        if not isinstance(self.tier, UniverseTier):
            raise TypeError("tier must be a UniverseTier")
        _require_text(self.universe_config_id, "universe_config_id")
        _require_text(self.membership_snapshot_id, "membership_snapshot_id")
        _require_text(self.membership_reason, "membership_reason")
        if not self.provenance:
            raise ValueError("membership provenance must not be empty")
        object.__setattr__(self, "provenance", _canonical_provenance(self.provenance))
        object.__setattr__(
            self,
            "membership_id",
            stable_content_hash(
                {
                    "type": "sentinel.universe_membership",
                    "version": "1",
                    "subject_id": self.subject_id,
                    "tier": self.tier,
                    "universe_config_id": self.universe_config_id,
                    "membership_snapshot_id": self.membership_snapshot_id,
                    "membership_reason": self.membership_reason,
                    "provenance": self.provenance,
                }
            ),
        )


@dataclass(frozen=True)
class ContextualActivation:
    """Explicit state describing a subject's temporary contextual scope."""

    __canonical_type_id__ = "sentinel.contextual_activation"
    __canonical_type_version__ = "1"

    subject_id: str
    activation_reason: str
    activated_at: datetime
    latest_material_confirmation_at: datetime
    ttl_days: int = 30
    expires_at: datetime = field(init=False)
    activation_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.subject_id, "subject_id")
        _require_text(self.activation_reason, "activation_reason")
        _require_aware(self.activated_at, "activated_at")
        _require_aware(
            self.latest_material_confirmation_at,
            "latest_material_confirmation_at",
        )
        if self.latest_material_confirmation_at < self.activated_at:
            raise ValueError("latest material confirmation cannot precede activation")
        if not isinstance(self.ttl_days, int) or isinstance(self.ttl_days, bool):
            raise TypeError("ttl_days must be an integer")
        if self.ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        expires_at = self.latest_material_confirmation_at + timedelta(days=self.ttl_days)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(
            self,
            "activation_id",
            stable_content_hash(
                {
                    "type": "sentinel.contextual_activation",
                    "version": "1",
                    "subject_id": self.subject_id,
                    "activation_reason": self.activation_reason,
                    "activated_at": self.activated_at,
                    "latest_material_confirmation_at": self.latest_material_confirmation_at,
                    "ttl_days": self.ttl_days,
                }
            ),
        )


class DiscoveryRejectionReason(str, Enum):
    """Canonical reasons recorded by a future discovery policy evaluator."""

    __canonical_type_id__ = "sentinel.discovery_rejection_reason"
    __canonical_type_version__ = "1"

    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    ILLIQUID = "ILLIQUID"
    MICROCAP = "MICROCAP"
    PENNY_STOCK = "PENNY_STOCK"
    UNSUPPORTED_SECURITY = "UNSUPPORTED_SECURITY"
    REDUNDANT_EXPOSURE = "REDUNDANT_EXPOSURE"


@dataclass(frozen=True)
class DiscoveryEligibility:
    """Result of discovery eligibility policy evaluation, without policy."""

    __canonical_type_id__ = "sentinel.discovery_eligibility"
    __canonical_type_version__ = "1"

    subject_id: str
    eligibility_config_id: str
    eligible: bool
    rejection_reasons: tuple[DiscoveryRejectionReason, ...]
    eligibility_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.subject_id, "subject_id")
        _require_text(self.eligibility_config_id, "eligibility_config_id")
        if not isinstance(self.eligible, bool):
            raise TypeError("eligible must be a bool")
        if any(not isinstance(reason, DiscoveryRejectionReason) for reason in self.rejection_reasons):
            raise TypeError("rejection_reasons must contain DiscoveryRejectionReason values")
        reasons = tuple(sorted(set(self.rejection_reasons), key=lambda reason: reason.value))
        object.__setattr__(self, "rejection_reasons", reasons)
        if self.eligible and reasons:
            raise ValueError("eligible subjects cannot have rejection reasons")
        if not self.eligible and not reasons:
            raise ValueError("ineligible subjects require at least one rejection reason")
        object.__setattr__(
            self,
            "eligibility_id",
            stable_content_hash(
                {
                    "type": "sentinel.discovery_eligibility",
                    "version": "1",
                    "subject_id": self.subject_id,
                    "eligibility_config_id": self.eligibility_config_id,
                    "eligible": self.eligible,
                    "rejection_reasons": self.rejection_reasons,
                }
            ),
        )


@dataclass(frozen=True)
class KnownInterestSnapshot:
    """Descriptive snapshot of known interests; never a discovery filter."""

    __canonical_type_id__ = "sentinel.known_interest_snapshot"
    __canonical_type_version__ = "1"

    as_of: datetime
    holding_subject_ids: tuple[str, ...] = ()
    watchlist_subject_ids: tuple[str, ...] = ()
    contextual_subject_ids: tuple[str, ...] = ()
    active_hypothesis_ids: tuple[str, ...] = ()
    recent_discovery_subject_ids: tuple[str, ...] = ()
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        set_like_fields = (
            "holding_subject_ids",
            "watchlist_subject_ids",
            "contextual_subject_ids",
            "active_hypothesis_ids",
            "recent_discovery_subject_ids",
        )
        for field_name in set_like_fields:
            values = getattr(self, field_name)
            for value in values:
                _require_text(value, field_name)
            object.__setattr__(self, field_name, tuple(sorted(set(values))))
        object.__setattr__(
            self,
            "snapshot_id",
            stable_content_hash(
                {
                    "type": "sentinel.known_interest_snapshot",
                    "version": "1",
                    "as_of": self.as_of,
                    **{field_name: getattr(self, field_name) for field_name in set_like_fields},
                }
            ),
        )
