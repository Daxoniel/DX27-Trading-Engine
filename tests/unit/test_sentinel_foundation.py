import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timedelta, timezone

import pytest

from dx27.intelligence.sentinel import (
    DataStatus,
    IdentityKind,
    ObservationWindow,
    Provenance,
    SubjectRef,
    canonical_json,
    make_content_identity,
    stable_content_hash,
)


def aware(hour: int = 12, tz=timezone.utc) -> datetime:
    return datetime(2026, 10, 6, hour, 30, tzinfo=tz)


@dataclass(frozen=True)
class RefactorBefore:
    __module__ = "legacy.sentinel.models"
    __canonical_type_id__ = "sentinel.test.contract"
    __canonical_type_version__ = "1"

    value: str


@dataclass(frozen=True)
class RefactorAfter:
    __module__ = "refactored.sentinel.contracts"
    __canonical_type_id__ = "sentinel.test.contract"
    __canonical_type_version__ = "1"

    value: str


@dataclass(frozen=True)
class DifferentCanonicalType:
    __canonical_type_id__ = "sentinel.test.other_contract"
    __canonical_type_version__ = "1"

    value: str


@dataclass(frozen=True)
class ContractVersionTwo:
    __canonical_type_id__ = "sentinel.test.contract"
    __canonical_type_version__ = "2"

    value: str


@dataclass(frozen=True)
class UntaggedModel:
    value: str


def test_foundation_models_are_immutable():
    subject = SubjectRef("us-equity:037833100", "EQUITY", symbol="AAPL")
    window = ObservationWindow(aware(10), aware(11), "1h")
    provenance = Provenance("fixture", aware())
    identity = make_content_identity(IdentityKind.SCHEMA, "foundation", "0.1", {})

    for model, field_name, value in (
        (subject, "symbol", "MSFT"),
        (window, "timeframe", "1d"),
        (provenance, "source_id", "changed"),
        (identity, "version", "0.2"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(model, field_name, value)


def test_equal_semantic_content_has_equal_canonical_json_and_identity():
    left = {
        "status": DataStatus.AVAILABLE,
        "subject": SubjectRef("us-equity:037833100", "EQUITY", symbol="AAPL"),
        "window": ObservationWindow(aware(10), aware(11), "1h"),
    }
    right = {
        "window": ObservationWindow(aware(10), aware(11), "1h"),
        "subject": SubjectRef("us-equity:037833100", "EQUITY", symbol="AAPL"),
        "status": DataStatus.AVAILABLE,
    }

    assert canonical_json(left) == canonical_json(right)
    assert stable_content_hash(left) == stable_content_hash(right)
    assert stable_content_hash(left) == stable_content_hash(left)


def test_mapping_insertion_order_does_not_change_identity():
    first = {"alpha": 1, "beta": {"x": 2, "y": 3}}
    second = {"beta": {"y": 3, "x": 2}, "alpha": 1}

    assert canonical_json(first) == canonical_json(second)
    assert stable_content_hash(first) == stable_content_hash(second)


def test_timestamp_identity_normalizes_equivalent_instants_to_utc():
    utc_value = aware(12)
    eastern_value = utc_value.astimezone(timezone(timedelta(hours=-4)))

    assert canonical_json(utc_value) == canonical_json(eastern_value)
    assert stable_content_hash(utc_value) == stable_content_hash(eastern_value)
    assert "2026-10-06T12:30:00.000000Z" in canonical_json(utc_value)


def test_different_semantic_content_changes_identity():
    base = SubjectRef("us-equity:037833100", "EQUITY", symbol="AAPL")
    changed = SubjectRef("us-equity:594918104", "EQUITY", symbol="MSFT")

    assert stable_content_hash(base) != stable_content_hash(changed)


def test_none_and_unavailable_are_explicit_and_not_zero_or_neutral():
    content = {"status": DataStatus.UNAVAILABLE, "value": None}
    serialized = canonical_json(content)

    assert '"value":null' in serialized
    assert "UNAVAILABLE" in serialized
    assert DataStatus.UNAVAILABLE.value not in {"0", "NEUTRAL", "NORMAL", "UNCHANGED"}
    assert len(DataStatus) == 6
    assert '"$enum":{"id":"sentinel.data_status","version":"1"}' in serialized


def test_canonical_models_use_explicit_stable_type_identifiers():
    subject_serialized = canonical_json(
        SubjectRef("us-equity:037833100", "EQUITY", symbol="AAPL")
    )

    assert '"id":"sentinel.subject_ref"' in subject_serialized
    assert '"version":"1"' in subject_serialized
    assert "dx27.intelligence.sentinel.models" not in subject_serialized


def test_canonical_identity_does_not_depend_on_python_module_path():
    before = RefactorBefore("same content")
    after = RefactorAfter("same content")

    assert type(before).__module__ != type(after).__module__
    assert canonical_json(before) == canonical_json(after)
    assert stable_content_hash(before) == stable_content_hash(after)


def test_different_canonical_model_types_cannot_collide_with_equal_fields():
    original = RefactorBefore("same content")
    different_type = DifferentCanonicalType("same content")

    assert canonical_json(original) != canonical_json(different_type)
    assert stable_content_hash(original) != stable_content_hash(different_type)


def test_changing_canonical_type_version_changes_serialization_and_identity():
    version_one = RefactorBefore("same content")
    version_two = ContractVersionTwo("same content")

    assert canonical_json(version_one) != canonical_json(version_two)
    assert stable_content_hash(version_one) != stable_content_hash(version_two)


def test_canonical_dataclass_cannot_fall_back_to_python_type_path():
    with pytest.raises(TypeError, match="stable type identifier"):
        canonical_json(UntaggedModel("content"))


def test_provenance_requires_explicit_source_and_aware_timestamp():
    provenance = Provenance("yahoo", aware(), source_record_id="AAPL:2026-10-06")

    assert provenance.source_id == "yahoo"
    with pytest.raises(ValueError, match="source_id"):
        Provenance("", aware())
    with pytest.raises(ValueError, match="timezone-aware"):
        Provenance("yahoo", datetime(2026, 10, 6, 12, 30))


def test_observation_window_rejects_naive_reversed_or_incomplete_bounds():
    naive = datetime(2026, 10, 6, 12, 30)

    with pytest.raises(ValueError, match="timezone-aware"):
        ObservationWindow(naive, aware(), "1d")
    with pytest.raises(ValueError, match="cannot precede"):
        ObservationWindow(aware(13), aware(12), "1h")
    with pytest.raises(ValueError, match="must be completed"):
        ObservationWindow(aware(12), aware(13), "1h", completed=False)


def test_sequence_order_is_preserved_and_unordered_collections_are_rejected():
    assert stable_content_hash(["A", "B"]) != stable_content_hash(["B", "A"])
    assert stable_content_hash(sorted(["B", "A"])) == stable_content_hash(["A", "B"])

    with pytest.raises(TypeError, match="canonicalized by the caller"):
        canonical_json({"A", "B"})


def test_float_policy_is_exact_finite_and_normalizes_signed_zero():
    assert canonical_json(0.0) == canonical_json(-0.0)
    assert "$float" in canonical_json(0.1)

    with pytest.raises(ValueError, match="finite"):
        canonical_json(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        canonical_json(float("inf"))


def test_configuration_identity_changes_with_effective_content():
    original = make_content_identity(
        IdentityKind.CONFIGURATION,
        "sentinel-foundation",
        "0.1",
        {"history": 20, "statuses": [DataStatus.AVAILABLE]},
    )
    repeated = make_content_identity(
        IdentityKind.CONFIGURATION,
        "sentinel-foundation",
        "0.1",
        {"statuses": [DataStatus.AVAILABLE], "history": 20},
    )
    changed = make_content_identity(
        IdentityKind.CONFIGURATION,
        "sentinel-foundation",
        "0.1",
        {"history": 21, "statuses": [DataStatus.AVAILABLE]},
    )

    assert original == repeated
    assert original.value.startswith("configuration:sentinel-foundation:0.1:")
    assert original != changed


def test_identity_does_not_depend_on_python_hash_randomization():
    script = """
from dx27.intelligence.sentinel import DataStatus, stable_content_hash
print(stable_content_hash({"symbols": ["SPY", "QQQ"], "status": DataStatus.AVAILABLE}))
"""
    results = []
    for seed in ("1", "999"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = "src"
        results.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=os.getcwd(),
                env=environment,
                text=True,
            ).strip()
        )

    assert results[0] == results[1]
