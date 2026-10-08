"""Exclusive-create raw captures and metadata; hashes detect subsequent edits."""

from datetime import datetime
import hashlib
import json
from pathlib import Path


def encoded(record):
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


class CaptureStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "captures").mkdir(parents=True, exist_ok=True)
        (self.root / "bindings").mkdir(exist_ok=True)

    def put(
        self,
        feed_id,
        source_id,
        url,
        raw,
        received_at,
        *,
        status=200,
        content_type="",
        error=None,
    ):
        if not isinstance(raw, bytes):
            raise TypeError("raw bytes required")
        if (
            not isinstance(received_at, datetime)
            or received_at.tzinfo is None
            or received_at.utcoffset() is None
        ):
            raise ValueError("aware actual response-completion time required")
        record = {
            "schema_version": "sentinel-capture-v1",
            "feed_id": feed_id,
            "source_id": source_id,
            "url": url,
            "first_seen_at": received_at.isoformat(),
            "published_at": None,
            "publication_evidence": "UNKNOWN_NOT_INFERRED",
            "http_status": status,
            "content_type": content_type,
            "error": error,
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        capture_id = hashlib.sha256(encoded(record)).hexdigest()
        path = self.root / "captures" / capture_id
        path.mkdir(exist_ok=False)
        for name, data in [
            ("payload.bin", raw),
            ("record.json", encoded(record)),
            ("seal.sha256", capture_id.encode()),
        ]:
            with (path / name).open("xb") as stream:
                stream.write(data)
        return {"capture_id": capture_id, **record}

    def get(self, capture_id):
        if len(capture_id) != 64 or any(
            c not in "0123456789abcdef" for c in capture_id
        ):
            raise ValueError("invalid capture ID")
        path = self.root / "captures" / capture_id
        raw = (path / "payload.bin").read_bytes()
        metadata = (path / "record.json").read_bytes()
        if (
            hashlib.sha256(metadata).hexdigest() != capture_id
            or (path / "seal.sha256").read_text() != capture_id
        ):
            raise ValueError("capture metadata/seal changed")
        record = json.loads(metadata)
        if (
            hashlib.sha256(raw).hexdigest() != record["payload_sha256"]
            or len(raw) != record["bytes"]
        ):
            raise ValueError("capture payload changed")
        return {"capture_id": capture_id, **record}, raw

    def records(self):
        # A directory with no seal is an incomplete write, not usable evidence.
        return tuple(
            self.get(p.name)[0]
            for p in sorted((self.root / "captures").iterdir())
            if p.is_dir()
        )

    def binding_record(self, feed_id, record=None):
        if not feed_id.isalnum() and "_" not in feed_id:
            raise ValueError("invalid feed ID")
        if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in feed_id):
            raise ValueError("invalid feed ID")
        path = self.root / "bindings" / (feed_id + ".json")
        if record is not None and not path.exists():
            try:
                with path.open("xb") as stream:
                    stream.write(
                        encoded(
                            {
                                "record": record,
                                "sha256": hashlib.sha256(encoded(record)).hexdigest(),
                            }
                        )
                    )
            except FileExistsError:
                pass
        if not path.exists():
            return None
        sealed = json.loads(path.read_bytes())
        existing = sealed["record"]
        if hashlib.sha256(encoded(existing)).hexdigest() != sealed["sha256"]:
            raise ValueError("binding record changed")
        # Binding identity anchors the FIRST verified capture, never each new fetch.
        captures = [self.get(i)[0] for i in existing["validation_capture_ids"]]
        if existing["validated_at"] != max(c["first_seen_at"] for c in captures):
            raise ValueError("binding validation time changed")
        if record is not None and existing["profile_id"] != record["profile_id"]:
            raise ValueError("new source profile requires a separately versioned store")
        return existing
