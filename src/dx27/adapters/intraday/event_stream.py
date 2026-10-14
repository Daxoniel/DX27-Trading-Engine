"""Bounded, resumable JSONL delivery source with byte-exact commit cursors."""

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from dx27.adapters.intraday.market_ingress import event_from_dict


@dataclass(frozen=True)
class StreamItem:
    event: object
    byte_offset: int
    line_number: int
    prefix_sha256: str


class EventQueue:
    def __init__(self, capacity):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 4096:
            raise ValueError('invalid bounded event capacity')
        self.capacity, self.items, self.peak, self.backpressure = capacity, deque(), 0, 0

    def offer(self, item):
        if len(self.items) == self.capacity:
            self.backpressure += 1
            return False  # The producer retains this item for a later retry.
        self.items.append(item)
        self.peak = max(self.peak, len(self.items))
        return True

    def pop(self):
        return self.items.popleft()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


class SealedEventFile:
    def __init__(self, path, source_sha, *, max_event_bytes=16384):
        if isinstance(max_event_bytes, bool) or not isinstance(max_event_bytes, int) or not 512 <= max_event_bytes <= 1_048_576:
            raise ValueError('invalid event byte limit')
        self.path, self.limit = Path(path), max_event_bytes
        self.file = self.path.open('rb')
        self.parsed = self.line_number = 0
        self.eof = False
        try:
            self.fingerprint = self._stat()
            digest = hashlib.sha256()
            for chunk in iter(lambda: self.file.read(1_048_576), b''):
                digest.update(chunk)
            self.sha256 = digest.hexdigest()
            self.assert_unchanged()
            self.size = self.fingerprint[2]
            metadata = self.path.with_suffix(self.path.suffix + '.metadata.json')
            if metadata.exists():
                seal = json.loads(metadata.read_text(encoding='utf-8'))
                if seal.get('events_file_sha256') != self.sha256 or seal.get('source_csv_sha256') != source_sha:
                    raise ValueError('event file/source seal mismatch')
            self.seek(dict(byte_offset=0, line_number=0, prefix_sha256=hashlib.sha256(b'').hexdigest()))
        except BaseException:
            self.file.close()
            raise

    def _stat(self):
        stat = os.fstat(self.file.fileno())
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def assert_unchanged(self):
        if self._stat() != self.fingerprint:
            raise ValueError('event source changed during reception')

    def seek(self, cursor):
        self.assert_unchanged()
        offset = cursor['byte_offset']
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= self.size:
            raise ValueError('invalid source byte cursor')
        self.file.seek(0)
        self.digest = hashlib.sha256()
        remaining = offset
        while remaining:
            raw = self.file.read(min(1_048_576, remaining))
            if not raw:
                raise ValueError('source prefix truncated')
            self.digest.update(raw)
            remaining -= len(raw)
        if self.digest.hexdigest() != cursor['prefix_sha256']:
            raise ValueError('source prefix differs from committed cursor')
        self.line_number = cursor['line_number']
        self.eof = False

    def next_item(self):
        self.assert_unchanged()
        while True:
            raw = self.file.readline(self.limit + 1)
            if len(raw) > self.limit:
                raise ValueError('event line exceeds bounded byte limit')
            if not raw:
                self.eof = True
                if self.digest.hexdigest() != self.sha256:
                    raise ValueError('event source content changed')
                return None
            self.line_number += 1
            self.digest.update(raw)
            if not raw.strip():
                continue
            event = event_from_dict(json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object))
            self.parsed += 1
            return StreamItem(event, self.file.tell(), self.line_number, self.digest.hexdigest())

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class EventPump:
    """At most capacity queued items plus one retained producer item."""

    def __init__(self, source, capacity):
        self.source, self.queue, self.pending = source, EventQueue(capacity), None

    def fill(self):
        while True:
            item = self.pending if self.pending is not None else self.source.next_item()
            if item is None:
                return
            if not self.queue.offer(item):
                self.pending = item
                return
            self.pending = None

    def peek(self):
        if not self.queue.items:
            self.fill()
        return self.queue.items[0] if self.queue.items else None

    def pop(self):
        item = self.peek()
        return self.queue.pop() if item is not None else None
