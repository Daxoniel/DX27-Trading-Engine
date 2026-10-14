"""Single-writer SQLite state transactions for bounded offline conformance."""

import hashlib
import json
from pathlib import Path
import sqlite3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def seal(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LifecycleJournal:
    """Commit derived state and audit hash together; rebuild no external actions."""

    def __init__(self, path, manifest, initial):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lease = self.db = None
        try:
            self.lease = sqlite3.connect(str(self.path) + ".lease.sqlite3", timeout=0)
            self.lease.execute("BEGIN EXCLUSIVE")
            self.db = sqlite3.connect(self.path, timeout=0)
            expected = canonical(manifest)
            has_metadata = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
            if has_metadata:
                current = self.db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
                if current is None or current[0] != expected:
                    raise ValueError("lifecycle namespace/initial account/contract mismatch")
            elif self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("unrecognized lifecycle database")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=DELETE")
            if not has_metadata:
                self.db.execute("BEGIN IMMEDIATE")
                with self.db:
                    self.db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    self.db.execute("CREATE TABLE audit (sequence INTEGER PRIMARY KEY, event TEXT NOT NULL, state_hash TEXT NOT NULL, chain TEXT NOT NULL)")
                    self.db.execute("INSERT INTO metadata VALUES ('manifest', ?)", (expected,))
                    self.db.execute("INSERT INTO metadata VALUES ('state', ?)", (canonical(initial),))
                    digest = seal(canonical(initial))
                    event = canonical(dict(kind="INITIALIZED"))
                    self.db.execute("INSERT INTO audit VALUES (1, ?, ?, ?)",
                                    (event, digest, seal("0" * 64 + "\n" + event + "\n" + digest)))
            self.sequence, self.chain, digest = 0, "0" * 64, None
            for sequence, event, digest, chain in self.db.execute("SELECT * FROM audit ORDER BY sequence"):
                self.sequence += 1
                if sequence != self.sequence or chain != seal(self.chain + "\n" + event + "\n" + digest):
                    raise ValueError("lifecycle audit integrity failure")
                self.chain = chain
            raw = self.db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            if raw is None or digest is None or digest != seal(raw[0]):
                raise ValueError("lifecycle state integrity failure")
            self.raw, self.state = raw[0], json.loads(raw[0])
        except BaseException:
            self.close()
            raise

    def save(self, state, event):
        raw, event = canonical(state), canonical(event)
        digest = seal(raw)
        chain = seal(self.chain + "\n" + event + "\n" + digest)
        with self.db:
            current = self.db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            if current is None or current[0] != self.raw:
                raise ValueError("lifecycle state changed outside its writer")
            self.db.execute("UPDATE metadata SET value=? WHERE key='state'", (raw,))
            self.db.execute("INSERT INTO audit VALUES (?, ?, ?, ?)", (self.sequence + 1, event, digest, chain))
        self.sequence, self.chain, self.raw, self.state = self.sequence + 1, chain, raw, state

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lease is not None:
            self.lease.close()
            self.lease = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
