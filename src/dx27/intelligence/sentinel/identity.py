"""Canonical serialization and deterministic content identities for Sentinel."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


class IdentityKind(str, Enum):
    __canonical_type_id__ = "sentinel.identity_kind"
    __canonical_type_version__ = "1"

    SCHEMA = "schema"
    MODEL = "model"
    CONFIGURATION = "configuration"


def _canonical_type(value: object) -> dict[str, str]:
    """Return the explicit semantic type identity declared by a model.

    Python import paths are implementation details and are deliberately not a
    fallback: every canonical enum or dataclass must opt into a stable type and
    contract version.
    """

    cls = type(value)
    type_id = cls.__dict__.get("__canonical_type_id__")
    version = cls.__dict__.get("__canonical_type_version__")
    if not isinstance(type_id, str) or not type_id.strip():
        raise TypeError("canonical enums and dataclasses require a stable type identifier")
    if not isinstance(version, str) or not version.strip():
        raise TypeError("canonical enums and dataclasses require a stable type version")
    return {"id": type_id, "version": version}


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical timestamps must be timezone-aware")
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_float(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("canonical floats must be finite")
    # Python considers positive and negative zero equal, so their canonical
    # representation must also be equal.  All other values use exact IEEE-754
    # hexadecimal form instead of locale-sensitive decimal formatting.
    if value == 0.0:
        value = 0.0
    return value.hex()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return {
            "$enum": _canonical_type(value),
            "value": _canonical_value(value.value),
        }
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return {"$float": _canonical_float(value)}
    if isinstance(value, datetime):
        return {"$datetime": _canonical_datetime(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "$dataclass": _canonical_type(value),
            "fields": {
                field.name: _canonical_value(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical mappings require string keys")
        return {
            key: _canonical_value(value[key])
            for key in sorted(value)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        # Sequence order is semantically meaningful.  Models with set-like
        # content must sort/canonicalize it before calling this function.
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError("unordered collections must be canonicalized by the caller")
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return canonical UTF-8 JSON text for supported immutable content."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def stable_content_hash(value: Any) -> str:
    """Return a lowercase SHA-256 digest of canonical content."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ContentIdentity:
    """Versioned identity for a schema, model, or effective configuration."""

    __canonical_type_id__ = "sentinel.content_identity"
    __canonical_type_version__ = "1"

    kind: IdentityKind
    name: str
    version: str
    digest: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("identity name must be a non-empty string")
        if not self.version.strip():
            raise ValueError("identity version must be a non-empty string")
        if len(self.digest) != 64 or any(char not in "0123456789abcdef" for char in self.digest):
            raise ValueError("identity digest must be a lowercase SHA-256 digest")

    @property
    def value(self) -> str:
        return f"{self.kind.value}:{self.name}:{self.version}:{self.digest}"


def make_content_identity(
    kind: IdentityKind,
    name: str,
    version: str,
    content: Any,
) -> ContentIdentity:
    """Identify versioned content without wall-clock or random input."""

    if not isinstance(kind, IdentityKind):
        raise TypeError("kind must be an IdentityKind")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("identity name must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("identity version must be a non-empty string")
    digest = stable_content_hash(
        {
            "content": content,
            "kind": kind,
            "name": name,
            "version": version,
        }
    )
    return ContentIdentity(kind=kind, name=name, version=version, digest=digest)
