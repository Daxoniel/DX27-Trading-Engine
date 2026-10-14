"""Freeze historical closed bars at declared receipt cutoffs, never backfill decisions."""

from bisect import bisect_right
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from functools import cached_property

from dx27.adapters.intraday.data import IntradayDataset
from dx27.adapters.intraday.recorded_shadow import _hash, _json
from dx27.application.intraday_replay import replay_sessions
from dx27.domains.intraday.market_event import MarketEvent


MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class IngressState:
    as_of: datetime
    connected: bool
    recovering: bool
    blocked_symbols: tuple[str, ...]


@dataclass(frozen=True)
class IngressRecord:
    as_of: datetime
    kind: str
    disposition: str
    event_id: str | None = None
    symbol: str | None = None
    bar_start: datetime | None = None
    revision: int = 0
    critical: bool = False
    payload_sha256: str | None = None


@dataclass(frozen=True)
class FrozenIngress:
    dataset: IntradayDataset
    states: tuple[IngressState, ...]
    records: tuple[IngressRecord, ...]
    context: tuple[tuple[str, object], ...]

    @property
    def manifest(self):
        return dict(self.context)

    @cached_property
    def state_times(self):
        return tuple(s.as_of for s in self.states)

    @cached_property
    def record_times(self):
        return tuple(r.as_of for r in self.records)

    @cached_property
    def complete(self):
        return not any(r.critical for r in self.records)

    def state_at(self, at):
        index = bisect_right(self.state_times, at) - 1
        return self.states[index] if index >= 0 else None

    def ready(self, symbol, at):
        state = self.state_at(at)
        return state is not None and state.connected and not state.recovering and symbol not in state.blocked_symbols

    def between(self, previous, at):
        start = bisect_right(self.record_times, previous) if previous is not None else 0
        return [asdict(r) for r in self.records[start:bisect_right(self.record_times, at)]]

    def validate(self, dataset):
        if dataset != self.dataset or dataset.provenance.get("market_ingress") != self.manifest:
            raise ValueError("ingress dataset/context mismatch")
        if self.manifest["states_sha256"] != _hash(_json([asdict(s) for s in self.states])) or self.manifest["records_sha256"] != _hash(_json([asdict(r) for r in self.records])):
            raise ValueError("ingress seal mismatch")

    def receipt(self):
        counts = Counter(r.disposition for r in self.records)
        return dict(task="P2-H4", status="COMPLETE_INGRESS" if self.complete else "INCOMPLETE_INGRESS",
                    **self.manifest, dispositions=dict(sorted(counts.items())),
                    frozen_bars=len(self.dataset.bars), real_broker_orders_enabled=False,
                    realtime_data_verified=False, algorithm_optimization_performed=False)


def session_grid(dataset):
    _, sessions = replay_sessions(dataset)
    symbols = tuple(sorted({b.symbol for b in dataset.bars} | set(dataset.provenance.get("symbols", ()))))
    grid = []
    for session in sessions:
        at = session.opens_at
        while at < session.closes_at:
            grid.append(at)
            at += MINUTE
    return symbols, tuple(grid)


class MinuteIngress:
    """Incremental H4 policy with interchangeable memory/durable maps.

    The caller closes a receipt-time group with a watermark only after every
    delivery in that group has been consumed. No full trace is required here.
    """

    SCALARS = ("connected", "recovering", "ever_connected", "active_connection",
               "anchor", "cursor", "last_received_at", "watermark", "event_count",
               "record_count", "critical_count")

    def __init__(self, source, symbols, grid, *, maps=None, state=None,
                 frozen=None, records=None, states=None):
        self.source = source.provenance.get("source", "LOCAL_CSV_UNVERIFIED")
        self.symbols, self.grid, self.expected = symbols, grid, set(grid)
        defaults = dict(candidates={}, raw_seen=set(), identities={}, cursors={},
                        versions={}, invalid=set(), gaps=set(), processed=set())
        for name, value in (defaults if maps is None else maps).items():
            setattr(self, name, value)
        self.frozen = [] if frozen is None else frozen
        self.records = [] if records is None else records
        self.states = [] if states is None else states
        self.connected = self.recovering = self.ever_connected = False
        self.active_connection = self.anchor = self.last_received_at = self.watermark = None
        self.cursor = self.event_count = self.record_count = self.critical_count = 0
        if state is not None:
            for name in self.SCALARS:
                value = state[name]
                if name in {"anchor", "last_received_at", "watermark"} and value is not None:
                    value = datetime.fromisoformat(value)
                setattr(self, name, value)

    def checkpoint(self):
        return {name: getattr(self, name) for name in self.SCALARS}

    def advance_before(self, at):
        if self.watermark is not None and at < self.watermark:
            raise ValueError("receipt watermark regressed")
        while self.cursor < len(self.grid) and self.grid[self.cursor] + MINUTE < at:
            self.freeze(self.grid[self.cursor])
            self.watermark = self.grid[self.cursor] + MINUTE
            self.cursor += 1

    def close_group(self, at):
        self.advance_before(at)
        if self.cursor < len(self.grid) and self.grid[self.cursor] + MINUTE == at:
            self.freeze(self.grid[self.cursor])
            self.cursor += 1
        else:
            self._snapshot(at)
        self.watermark = at

    def finish(self):
        while self.cursor < len(self.grid):
            self.freeze(self.grid[self.cursor])
            self.watermark = self.grid[self.cursor] + MINUTE
            self.cursor += 1

    def _record(self, at, kind, disposition, event=None, symbol=None, start=None, critical=False):
        self.record_count += 1
        self.critical_count += int(critical)
        self.records.append(IngressRecord(at, kind, disposition, event.event_id if event else None,
            symbol if symbol is not None else event.bar.symbol if event and event.bar else None,
            start if start is not None else event.bar.timestamp if event and event.bar else None,
            event.revision if event else 0, critical,
            _hash(_json(asdict(event))) if event else None))

    def _snapshot(self, at, missing=()):
        blocked = set(self.symbols) if not self.connected or self.recovering else self.invalid | set(missing)
        value = IngressState(at, self.connected, self.recovering, tuple(sorted(blocked)))
        if self.states and self.states[-1].as_of == at:
            self.states[-1] = value
        else:
            self.states.append(value)

    def freeze(self, start):
        missing = []
        for symbol in self.symbols:
            key = (symbol, start)
            event = self.candidates.pop(key, None)
            if event is None:
                missing.append(symbol)
                self.gaps.add(key)
                self.recovering = True
                self.anchor = start if self.anchor is None else min(self.anchor, start)
                self._record(start + MINUTE, "CUTOFF", "MISSING_BAR", symbol=symbol, start=start, critical=True)
            else:
                self.frozen.append(event.bar)
        self._snapshot(start + MINUTE, missing)

    def consume(self, event):
        if not isinstance(event, MarketEvent) or event.source != self.source:
            raise ValueError("event source/type mismatch")
        if self.last_received_at is not None and event.received_at < self.last_received_at:
            raise ValueError("receipt clock regressed")
        if self.watermark is not None and event.received_at <= self.watermark:
            raise ValueError("delivery at or before a closed receipt watermark")
        if event.bar is not None and (event.bar.symbol not in self.symbols or event.bar.timestamp not in self.expected):
            raise ValueError("bar outside declared regular-session universe")
        self.last_received_at = event.received_at
        self.event_count += 1
        content = dict(kind=event.kind, source=event.source, available_at=event.available_at,
                       bar=asdict(event.bar) if event.bar else None, revision=event.revision, through=event.through)
        identity = _hash(_json(content))
        prior = self.identities.get(event.event_id)
        if prior is not None and prior != identity:
            raise ValueError("event identity conflict")
        last_seq, _ = self.cursors.get(event.connection, (0, None))
        if event.event_id in self.processed and event.sequence <= last_seq:
            self._record(event.received_at, event.kind, "DUPLICATE_DELIVERY", event)
            return
        if event.sequence <= last_seq:
            raise ValueError("connection sequence regressed or conflicted")
        if event.sequence != last_seq + 1:
            self.recovering = True
            self.anchor = self.grid[0] if self.anchor is None else self.anchor
            self._record(event.received_at, event.kind, "SEQUENCE_GAP", event, critical=True)
        self.cursors[event.connection] = (event.sequence, event.event_id)
        self.identities[event.event_id] = identity
        if event.event_id in self.processed:
            self._record(event.received_at, event.kind, "DUPLICATE_DELIVERY", event)
            return
        if event.kind == "CONNECT":
            self.processed.add(event.event_id)
            if self.connected and self.active_connection != event.connection:
                self.recovering = True
                self._record(event.received_at, event.kind, "UNANNOUNCED_CONNECTION_CHANGE", event, critical=True)
            if self.ever_connected:
                self.recovering = True
            self.connected, self.ever_connected, self.active_connection = True, True, event.connection
            self._record(event.received_at, event.kind, "CONNECTED", event)
            return
        if event.connection != self.active_connection or not self.connected:
            self._record(event.received_at, event.kind, "INACTIVE_CONNECTION", event, critical=True)
            self.recovering = True
            return
        self.processed.add(event.event_id)
        if event.kind == "DISCONNECT":
            self.connected, self.recovering = False, True
            self.anchor = event.received_at.replace(second=0, microsecond=0)
            self._record(event.received_at, event.kind, "DISCONNECTED", event, critical=True)
            return
        if event.kind == "SYNC":
            required = {(s, t) for t in self.grid if t + MINUTE <= event.through and (self.anchor is None or t >= self.anchor) for s in self.symbols}
            required |= {key for key in self.gaps if key[1] + MINUTE <= event.through}
            if event.through < event.received_at.replace(second=0, microsecond=0) or not required.issubset(self.raw_seen):
                self.recovering = True
                self._record(event.received_at, event.kind, "SYNC_INCOMPLETE", event, critical=True)
            else:
                self.recovering, self.anchor = False, None
                self._record(event.received_at, event.kind, "SYNCHRONIZED", event)
            return
        key = (event.bar.symbol, event.bar.timestamp)
        prior_bar = self.versions.get(key)
        bar_hash = _hash(_json(asdict(event.bar)))
        if prior_bar is not None:
            revision, prior_hash = prior_bar
            if event.revision < revision:
                self._record(event.received_at, event.kind, "STALE_REVISION", event)
                return
            if event.revision == revision:
                if prior_hash != bar_hash:
                    self.invalid.add(event.bar.symbol)
                    self.candidates.pop(key, None)
                    self._record(event.received_at, event.kind, "REVISION_CONFLICT", event, critical=True)
                else:
                    self._record(event.received_at, event.kind, "DUPLICATE_BAR", event)
                return
        self.raw_seen.add(key)
        self.gaps.discard(key)
        self.versions[key] = (event.revision, bar_hash)
        if event.received_at > event.bar.timestamp + MINUTE:
            if prior_bar is not None:
                self.invalid.add(event.bar.symbol)
                disposition = "POST_CUTOFF_REVISION"
            else:
                self.recovering = True
                self.anchor = event.bar.timestamp if self.anchor is None else min(self.anchor, event.bar.timestamp)
                disposition = "LATE_BAR"
            self._record(event.received_at, event.kind, disposition, event, critical=True)
            return
        self.candidates[key] = event
        self._record(event.received_at, event.kind, "REVISED_BEFORE_FREEZE" if prior_bar else "ACCEPTED", event)


def compile_ingress(source, deliveries):
    """Compatibility compiler using the same incremental policy as P2-H5."""
    events = tuple(deliveries)
    symbols, grid = session_grid(source)
    machine = MinuteIngress(source, symbols, grid)
    index = 0
    while index < len(events):
        at = events[index].received_at
        machine.advance_before(at)
        while index < len(events) and events[index].received_at == at:
            machine.consume(events[index])
            index += 1
        machine.close_group(at)
    machine.finish()
    frozen, records, states = machine.frozen, machine.records, machine.states
    # All records are in receipt/cutoff order, including events after the last close.
    context = dict(contract="P2-H4:1", event_count=len(events), input_event_sha256=_hash(_json([asdict(e) for e in events])),
                   states_sha256=_hash(_json([asdict(s) for s in states])),
                   records_sha256=_hash(_json([asdict(r) for r in records])),
                   source_csv_sha256=source.provenance.get("csv_sha256"), source_input_bars=len(source.bars),
                   cutoff_policy="EXACT_MINUTE_END_ZERO_GRACE", feed_scope="REGULAR_XNYS_SESSIONS",
                   receipt_times="DECLARED_HISTORICAL_NOT_VERIFIED_REALTIME", original_cutoff_verified=False)
    provenance = dict(source.provenance, symbols=list(symbols), market_ingress=context)
    if not provenance.get("start"):
        # Freeze the source's whole scheduled horizon, even when an entire
        # final session has no admitted deliveries and disappears from bars.
        provenance.update(start=grid[0].isoformat(), end_exclusive=(grid[-1] + MINUTE).isoformat())
    dataset = IntradayDataset(tuple(sorted(frozen, key=lambda b: (b.timestamp, b.symbol))), provenance)
    return FrozenIngress(dataset, tuple(states), tuple(records), tuple(sorted(context.items())))
