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


def compile_ingress(source, deliveries):
    """Source CSV supplies universe/calendar only; accepted event OHLCV is authoritative.

    Input is in receipt order. A full same-clock delivery group precedes freezing
    that deadline, with zero grace. Late data is retained in audit/coverage only.
    """
    events = tuple(deliveries)
    symbols, grid = session_grid(source)
    expected = set(grid)
    declared_source = source.provenance.get("source", "LOCAL_CSV_UNVERIFIED")
    for index, event in enumerate(events):
        if not isinstance(event, MarketEvent) or event.source != declared_source:
            raise ValueError("event source/type mismatch")
        if index and event.received_at < events[index - 1].received_at:
            raise ValueError("receipt clock regressed")
        if event.bar is not None and (event.bar.symbol not in symbols or event.bar.timestamp not in expected):
            raise ValueError("bar outside declared regular-session universe")
    candidates, raw_seen, identities, cursors, versions = {}, set(), {}, {}, {}
    frozen, records, states, invalid, gaps = [], [], [], set(), set()
    processed = set()
    connected, recovering, ever_connected, active_connection = False, False, False, None
    anchor = None
    cursor = 0

    def record(at, kind, disposition, event=None, symbol=None, start=None, critical=False):
        records.append(IngressRecord(at, kind, disposition, event.event_id if event else None,
            symbol if symbol is not None else event.bar.symbol if event and event.bar else None,
            start if start is not None else event.bar.timestamp if event and event.bar else None,
            event.revision if event else 0, critical,
            _hash(_json(asdict(event))) if event else None))

    def snapshot(at, missing=()):
        blocked = set(symbols) if not connected or recovering else invalid | set(missing)
        value = IngressState(at, connected, recovering, tuple(sorted(blocked)))
        if states and states[-1].as_of == at:
            states[-1] = value
        else:
            states.append(value)

    def freeze(start):
        nonlocal recovering, anchor
        missing = []
        for symbol in symbols:
            key = (symbol, start)
            event = candidates.pop(key, None)
            if event is None:
                missing.append(symbol)
                gaps.add(key)
                recovering = True
                anchor = start if anchor is None else min(anchor, start)
                record(start + MINUTE, "CUTOFF", "MISSING_BAR", symbol=symbol, start=start, critical=True)
            else:
                frozen.append(event.bar)
        snapshot(start + MINUTE, missing)

    def consume(event):
        nonlocal connected, recovering, ever_connected, active_connection, anchor
        content = dict(kind=event.kind, source=event.source, available_at=event.available_at,
                       bar=asdict(event.bar) if event.bar else None, revision=event.revision, through=event.through)
        identity = _hash(_json(content))
        prior = identities.get(event.event_id)
        if prior is not None and prior != identity:
            raise ValueError("event identity conflict")
        last_seq, _ = cursors.get(event.connection, (0, None))
        if event.event_id in processed and event.sequence <= last_seq:
            record(event.received_at, event.kind, "DUPLICATE_DELIVERY", event)
            return
        if event.sequence <= last_seq:
            raise ValueError("connection sequence regressed or conflicted")
        if event.sequence != last_seq + 1:
            recovering = True
            anchor = grid[0] if anchor is None else anchor
            record(event.received_at, event.kind, "SEQUENCE_GAP", event, critical=True)
        cursors[event.connection] = (event.sequence, event.event_id)
        identities[event.event_id] = identity
        if event.event_id in processed:
            record(event.received_at, event.kind, "DUPLICATE_DELIVERY", event)
            return
        if event.kind == "CONNECT":
            processed.add(event.event_id)
            if connected and active_connection != event.connection:
                recovering = True
                record(event.received_at, event.kind, "UNANNOUNCED_CONNECTION_CHANGE", event, critical=True)
            if ever_connected:
                recovering = True
            connected, ever_connected, active_connection = True, True, event.connection
            record(event.received_at, event.kind, "CONNECTED", event)
            return
        if event.connection != active_connection or not connected:
            record(event.received_at, event.kind, "INACTIVE_CONNECTION", event, critical=True)
            recovering = True
            return
        processed.add(event.event_id)
        if event.kind == "DISCONNECT":
            connected, recovering = False, True
            anchor = event.received_at.replace(second=0, microsecond=0)
            record(event.received_at, event.kind, "DISCONNECTED", event, critical=True)
            return
        if event.kind == "SYNC":
            required = {(s, t) for t in grid if t + MINUTE <= event.through and (anchor is None or t >= anchor) for s in symbols}
            required |= {key for key in gaps if key[1] + MINUTE <= event.through}
            if event.through < event.received_at.replace(second=0, microsecond=0) or not required.issubset(raw_seen):
                recovering = True
                record(event.received_at, event.kind, "SYNC_INCOMPLETE", event, critical=True)
            else:
                recovering, anchor = False, None
                record(event.received_at, event.kind, "SYNCHRONIZED", event)
            return
        key = (event.bar.symbol, event.bar.timestamp)
        prior_bar = versions.get(key)
        bar_hash = _hash(_json(asdict(event.bar)))
        if prior_bar is not None:
            revision, prior_hash = prior_bar
            if event.revision < revision:
                record(event.received_at, event.kind, "STALE_REVISION", event)
                return
            if event.revision == revision:
                if prior_hash != bar_hash:
                    invalid.add(event.bar.symbol)
                    candidates.pop(key, None)
                    record(event.received_at, event.kind, "REVISION_CONFLICT", event, critical=True)
                else:
                    record(event.received_at, event.kind, "DUPLICATE_BAR", event)
                return
        raw_seen.add(key)
        gaps.discard(key)
        versions[key] = (event.revision, bar_hash)
        if event.received_at > event.bar.timestamp + MINUTE:
            if prior_bar is not None:
                invalid.add(event.bar.symbol)
                disposition = "POST_CUTOFF_REVISION"
            else:
                recovering = True
                anchor = event.bar.timestamp if anchor is None else min(anchor, event.bar.timestamp)
                disposition = "LATE_BAR"
            record(event.received_at, event.kind, disposition, event, critical=True)
            return
        candidates[key] = event
        record(event.received_at, event.kind, "REVISED_BEFORE_FREEZE" if prior_bar else "ACCEPTED", event)

    index = 0
    while index < len(events):
        at = events[index].received_at
        while cursor < len(grid) and grid[cursor] + MINUTE < at:
            freeze(grid[cursor])
            cursor += 1
        while index < len(events) and events[index].received_at == at:
            consume(events[index])
            index += 1
        if cursor < len(grid) and grid[cursor] + MINUTE == at:
            freeze(grid[cursor])
            cursor += 1
        else:
            snapshot(at)
    while cursor < len(grid):
        freeze(grid[cursor])
        cursor += 1
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
