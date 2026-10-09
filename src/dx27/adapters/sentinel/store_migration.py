"""Byte-exact offline store backup/restore. No timestamp or pilot rewrite."""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

from dx27.adapters.sentinel.capture_store import CaptureStore, encoded
from dx27.adapters.sentinel.file_lock import exclusive_lock
from dx27.adapters.sentinel.coverage_pilot import read_job

TRANSIENT = {
    "heartbeat.json",
    "heartbeat.tmp",
    "health.json",
    "health.tmp",
    "supervisor-health.json",
    "supervisor-ledger.json",
    "supervisor-health.tmp",
}


def verify_store(root):
    root = Path(root)
    if not root.is_dir() or not (root / "captures").is_dir():
        raise ValueError("existing capture store required")
    store = CaptureStore(root)
    records = store.records()
    for directory in [root / "bindings", *root.glob("profiles/*/bindings")]:
        for path in directory.glob("*.json"):
            # Profile binding evidence resides in the common raw journal.
            sealed = json.loads(path.read_bytes())
            record = sealed["record"]
            if hashlib.sha256(encoded(record)).hexdigest() != sealed["sha256"]:
                raise ValueError("binding seal changed")
            captures = [store.get(i)[0] for i in record["validation_capture_ids"]]
            if record["validated_at"] != max(c["first_seen_at"] for c in captures):
                raise ValueError("binding validation time changed")
    for path in root.glob("profiles/*/jobs/*.json"):
        read_job(path)
    for path in root.glob("profiles/*/coverage/*.json"):
        if hashlib.sha256(path.read_bytes()).hexdigest() != path.stem:
            raise ValueError("coverage hash changed")
    return records


def portable_files(root):
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in store")
        if (
            path.is_file()
            and path.name not in TRANSIENT
            and not path.name.endswith(".lock")
        ):
            files.append(path)
    return files


def backup(root, archive):
    root = Path(root)
    archive = Path(archive)
    if archive.resolve().is_relative_to(root.resolve()):
        raise ValueError("archive must be outside store")
    # Caller quiesces all writers. Locks reject any currently active pilot worker.
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(exclusive_lock(root / "supervisor.lock"))
        for path in sorted(root.glob("profiles/*/worker.lock")):
            stack.enter_context(exclusive_lock(path))
        records = verify_store(root)
        files = portable_files(root)
        content = {p.relative_to(root).as_posix(): p.read_bytes() for p in files}
        manifest = {
            "schema_version": "sentinel-store-migration-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "capture_count": len(records),
            "files": {
                name: hashlib.sha256(raw).hexdigest() for name, raw in content.items()
            },
            "policy": "Preserve original bytes/times, bindings, configuration, jobs and reports. Heartbeats/locks are process-local and excluded.",
        }
        with archive.open("xb") as stream:
            try:
                archive.chmod(0o600)
            except OSError:
                pass
            with tarfile.open(fileobj=stream, mode="w:gz") as tar:
                for name, raw in {
                    "migration-manifest.json": encoded(manifest),
                    **{"store/" + name: raw for name, raw in content.items()},
                }.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    info.mode = 0o600
                    tar.addfile(info, io.BytesIO(raw))
        return manifest


def restore(archive, target):
    target = Path(target)
    if target.exists():
        raise ValueError("restore requires a new target directory")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len({m.name for m in members}) != len(members):
            raise ValueError("duplicate archive names")
        if any(
            not m.isfile()
            or PurePosixPath(m.name).is_absolute()
            or ".." in PurePosixPath(m.name).parts
            for m in members
        ):
            raise ValueError("unsafe archive member")
        manifest = json.loads(tar.extractfile("migration-manifest.json").read())
        if manifest["schema_version"] != "sentinel-store-migration-v1":
            raise ValueError("migration schema mismatch")
        expected = {
            "migration-manifest.json",
            *("store/" + name for name in manifest["files"]),
        }
        if {m.name for m in members} != expected:
            raise ValueError("unexpected archive content")
        content = {
            name: tar.extractfile("store/" + name).read() for name in manifest["files"]
        }
        for name, raw in content.items():
            if (
                not PurePosixPath(name).parts
                or "\\" in name
                or ":" in name
                or ".." in PurePosixPath(name).parts
                or PurePosixPath(name).is_absolute()
            ):
                raise ValueError("unsafe store path")
            if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
                raise ValueError("migration checksum changed")
    target.mkdir(parents=True, exist_ok=False)
    for name, raw in content.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    records = verify_store(target)
    if len(records) != manifest["capture_count"]:
        raise ValueError("capture count changed")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    export = subs.add_parser("backup")
    export.add_argument("--store", type=Path, required=True)
    export.add_argument("--archive", type=Path, required=True)
    load = subs.add_parser("restore")
    load.add_argument("--archive", type=Path, required=True)
    load.add_argument("--store", type=Path, required=True)
    verify = subs.add_parser("verify")
    verify.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "backup":
        result = backup(args.store, args.archive)
    elif args.action == "restore":
        result = restore(args.archive, args.store)
    else:
        result = {"capture_count": len(verify_store(args.store))}
    print(
        json.dumps(
            result
            if args.action == "verify"
            else {
                "capture_count": result["capture_count"],
                "files": len(result["files"]),
            }
        )
    )


if __name__ == "__main__":
    main()
