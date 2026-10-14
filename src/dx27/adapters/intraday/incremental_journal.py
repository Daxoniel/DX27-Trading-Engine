"""Atomic incremental receiver maps/checkpoints alongside shadow minute batches."""

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json

from dx27.adapters.intraday.market_ingress import event_from_dict
from dx27.adapters.intraday.recorded_shadow import ShadowJournal, _hash, _json
from dx27.application.market_ingress import IngressRecord, IngressState


SPACES = ('candidates', 'raw_seen', 'identities', 'cursors', 'versions', 'invalid',
          'gaps', 'processed', 'states', 'records')


def clock_key(at):
    return at.astimezone(timezone.utc).isoformat(timespec='microseconds')


def decode_record(value):
    value = dict(value)
    for name in ('as_of', 'bar_start'):
        if value[name] is not None:
            value[name] = datetime.fromisoformat(value[name])
    return IngressRecord(**value)


class ReceiverJournal(ShadowJournal):
    """Map integrity uses domain-separated row SHA256 XOR plus row count.

    Each checkpoint binds the aggregate and small control/cursor state to the
    existing ordered shadow frame hash chain, in the same SQLite transaction.
    Maps stay on disk; the checkpoint does not copy all prior delivery IDs.
    """

    def __init__(self, path, manifest):
        super().__init__(path, manifest)
        try:
            if not self.existing:
                with self.connection:
                    self.connection.execute('CREATE TABLE IF NOT EXISTS receiver_rows (space TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(space,key))')
            self.accumulator, self.row_count = 0, 0
            for space, key, value in self.connection.execute('SELECT space,key,value FROM receiver_rows'):
                if space not in SPACES or _json(json.loads(value)) != value:
                    raise ValueError('receiver map integrity failure')
                self.accumulator ^= self.row_hash(space, key, value)
                self.row_count += 1
            row = self.connection.execute("SELECT value FROM metadata WHERE key='receiver_checkpoint'").fetchone()
            self.checkpoint = json.loads(row[0]) if row else None
            if self.existing:
                latest = json.loads(self.connection.execute('SELECT payload FROM frames ORDER BY sequence DESC LIMIT 1').fetchone()[0])
                if latest.get('receiver_checkpoint') != self.checkpoint:
                    raise ValueError('receiver checkpoint differs from committed shadow frame')
            if not self.existing and self.checkpoint is not None:
                raise ValueError("receiver checkpoint without committed shadow frames")
            if self.checkpoint is not None:
                if self.checkpoint['maps'] != self.map_seal():
                    raise ValueError('receiver map integrity failure')
            elif self.existing or self.row_count:
                raise ValueError('receiver maps without committed checkpoint')
        except BaseException:
            self.close()
            raise

    @staticmethod
    def row_hash(space, key, value):
        return int(_hash(space + '\n' + key + '\n' + value), 16)

    def map_seal(self):
        return dict(sha256_xor=f'{self.accumulator:064x}', rows=self.row_count)

    def begin(self):
        if not self.connection.in_transaction:
            self.connection.execute('BEGIN IMMEDIATE')

    def get_row(self, space, key):
        row = self.connection.execute('SELECT value FROM receiver_rows WHERE space=? AND key=?', (space, _json(key))).fetchone()
        return json.loads(row[0]) if row else None

    def put_row(self, space, key, value):
        self.begin()
        key = _json(key)
        value = _json(asdict(value) if is_dataclass(value) else value)
        old = self.connection.execute('SELECT value FROM receiver_rows WHERE space=? AND key=?', (space, key)).fetchone()
        if old and old[0] == value:
            return
        if old:
            self.accumulator ^= self.row_hash(space, key, old[0])
        else:
            self.row_count += 1
        self.accumulator ^= self.row_hash(space, key, value)
        self.connection.execute('INSERT INTO receiver_rows VALUES (?,?,?) ON CONFLICT(space,key) DO UPDATE SET value=excluded.value', (space, key, value))

    def remove_row(self, space, key):
        self.begin()
        key = _json(key)
        old = self.connection.execute('SELECT value FROM receiver_rows WHERE space=? AND key=?', (space, key)).fetchone()
        if old:
            self.accumulator ^= self.row_hash(space, key, old[0])
            self.row_count -= 1
            self.connection.execute('DELETE FROM receiver_rows WHERE space=? AND key=?', (space, key))

    def seal_checkpoint(self, value):
        self.begin()
        value = dict(value, maps=self.map_seal())
        self.connection.execute("INSERT INTO metadata VALUES ('receiver_checkpoint',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_json(value),))
        self.checkpoint = json.loads(_json(value))
        return self.checkpoint

    def stored_frame(self, kind, at):
        row = self.connection.execute('SELECT payload FROM frames WHERE frame_key=?', (kind + ':' + at.isoformat(),)).fetchone()
        return json.loads(row[0]) if row else None

    def state_at(self, at):
        row = self.connection.execute("SELECT value FROM receiver_rows WHERE space='states' AND key<=? ORDER BY key DESC LIMIT 1", (_json(clock_key(at)),)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        return IngressState(datetime.fromisoformat(value['as_of']), value['connected'], value['recovering'], tuple(value['blocked_symbols']))

    def records_after(self, sequence, at=None):
        for key, raw in self.connection.execute("SELECT key,value FROM receiver_rows WHERE space='records' AND CAST(key AS INTEGER)>? ORDER BY CAST(key AS INTEGER)", (sequence,)):
            value = json.loads(raw)
            if at is not None and datetime.fromisoformat(value['as_of']) > at:
                break
            yield int(key), value


class DurableMap:
    def __init__(self, journal, space):
        self.journal, self.space = journal, space

    def get(self, key, default=None):
        value = self.journal.get_row(self.space, key)
        if value is None:
            return default
        return event_from_dict(value) if self.space == 'candidates' else value

    def __contains__(self, key):
        return self.journal.get_row(self.space, key) is not None

    def __setitem__(self, key, value):
        self.journal.put_row(self.space, key, value)

    def pop(self, key, default=None):
        value = self.get(key, default)
        self.journal.remove_row(self.space, key)
        return value

    def add(self, key):
        self[key] = True

    def discard(self, key):
        self.journal.remove_row(self.space, key)

    def __iter__(self):
        for row in self.journal.connection.execute('SELECT key FROM receiver_rows WHERE space=?', (self.space,)):
            key = json.loads(row[0])
            yield (key[0], datetime.fromisoformat(key[1])) if isinstance(key, list) else key

    def __or__(self, other):
        return set(self) | set(other)


class StateSink:
    def __init__(self, journal):
        self.journal = journal

    def __bool__(self):
        return self.journal.connection.execute("SELECT 1 FROM receiver_rows WHERE space='states' LIMIT 1").fetchone() is not None

    def __getitem__(self, index):
        if index != -1:
            raise IndexError('only latest state is supported')
        row = self.journal.connection.execute("SELECT value FROM receiver_rows WHERE space='states' ORDER BY key DESC LIMIT 1").fetchone()
        value = json.loads(row[0])
        return IngressState(datetime.fromisoformat(value['as_of']), value['connected'], value['recovering'], tuple(value['blocked_symbols']))

    def __setitem__(self, index, value):
        if index != -1:
            raise IndexError('only latest state is supported')
        self.append(value)

    def append(self, value):
        self.journal.put_row('states', clock_key(value.as_of), value)


class RecordSink:
    def __init__(self, journal, start):
        self.journal, self.sequence = journal, start

    def append(self, value):
        self.sequence += 1
        self.journal.put_row('records', self.sequence, value)
