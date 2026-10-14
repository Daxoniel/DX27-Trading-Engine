"""P2-H5 incremental historical input and shadow simulation, with durable cursors."""

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import signal
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from dx27.adapters.intraday.cli import read_config, write_report
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.event_stream import EventPump, EventQueue, SealedEventFile
from dx27.adapters.intraday.incremental_journal import DurableMap, RecordSink, ReceiverJournal, StateSink, decode_record
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.recorded_shadow import _hash, _json, manifest_for
from dx27.adapters.intraday.runner import _atomic_json, _now, _owner, health, request_stop
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.application.intraday_closed_loop import ClosedLoopReplay
from dx27.application.market_ingress import MinuteIngress, session_grid
from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.replay_config import IntradayReplayConfig


MINUTE = timedelta(minutes=1)


class BarSink:
    def __init__(self):
        self.bars = {}

    def append(self, bar):
        self.bars[bar.symbol] = bar


def decode_bar(value):
    value = dict(value)
    value['timestamp'] = datetime.fromisoformat(value['timestamp'])
    return MarketContext(**value)


class IncrementalReceiver:
    def __init__(self, store, source, event_file, capacity, hook=None):
        self.store, self.event_file, self.capacity, self.hook = store, event_file, capacity, hook
        symbols, grid = session_grid(source)
        checkpoint = store.checkpoint
        self.cursor = checkpoint['source_cursor'] if checkpoint else dict(byte_offset=0, line_number=0, prefix_sha256=hashlib.sha256(b'').hexdigest())
        self.eof = checkpoint['eof'] if checkpoint else False
        self.bar_sink = BarSink()
        self.pump, self.packet = None, None
        self.maps = {name: DurableMap(store, name) for name in ('candidates', 'raw_seen', 'identities', 'cursors', 'versions', 'invalid', 'gaps', 'processed')}
        self.machine = MinuteIngress(source, symbols, grid, maps=self.maps,
            state=checkpoint['control'] if checkpoint else None, frozen=self.bar_sink,
            records=RecordSink(store, checkpoint['control']['record_count'] if checkpoint else 0), states=StateSink(store))
        self.last_audit = 0

    def ensure_pump(self):
        if self.pump is None:
            self.event_file.seek(self.cursor)
            self.pump = EventPump(self.event_file, self.capacity)

    def checkpoint(self):
        return dict(control=self.machine.checkpoint(), source_cursor=self.cursor, eof=self.eof)

    def group(self):
        self.ensure_pump()
        first = self.pump.peek()
        if first is None:
            return False
        at = first.event.received_at
        self.machine.advance_before(at)
        while (item := self.pump.peek()) is not None and item.event.received_at == at:
            item = self.pump.pop()
            self.machine.consume(item.event)
            self.cursor = dict(byte_offset=item.byte_offset, line_number=item.line_number, prefix_sha256=item.prefix_sha256)
            if self.hook:
                self.hook('EVENT_CONSUMED', dict(events=self.machine.event_count, at=at.isoformat()))
        self.machine.close_group(at)
        return True

    def get(self, start, default=None):
        end = start + MINUTE
        stored = self.store.stored_frame('MINUTE_COMPLETED', end)
        if stored is not None:
            self.packet = stored['market_input']
            return {value['symbol']: decode_bar(value) for value in self.packet['bars']}
        self.store.begin()
        self.bar_sink.bars.clear()
        self.ensure_pump()
        while (item := self.pump.peek()) is not None and item.event.received_at <= end:
            self.group()
        if self.machine.watermark is None or self.machine.watermark < end:
            self.machine.close_group(end)
        self.packet = dict(as_of=end.isoformat(), bars=[asdict(bar) for bar in self.bar_sink.bars.values()])
        return dict(self.bar_sink.bars)

    def finish(self):
        if self.eof:
            return
        self.store.begin()
        self.ensure_pump()
        while self.group():
            pass
        self.machine.finish()
        self.event_file.assert_unchanged()
        self.cursor = dict(byte_offset=self.event_file.size, line_number=self.event_file.line_number, prefix_sha256=self.event_file.sha256)
        self.eof = True

    def audit(self, at):
        output = []
        for sequence, value in self.store.records_after(self.last_audit, at):
            output.append(value)
            self.last_audit = sequence
        return output


class ReceiverView:
    def __init__(self, receiver):
        self.receiver = receiver

    def state_at(self, at):
        return self.receiver.store.state_at(at)

    def ready(self, symbol, at):
        value = self.state_at(at)
        return value is not None and value.connected and not value.recovering and symbol not in value.blocked_symbols

    @property
    def complete(self):
        return self.receiver.eof and self.receiver.machine.critical_count == 0

    @property
    def records(self):
        return (decode_record(value) for _, value in self.receiver.store.records_after(0))

    def receipt(self):
        counts = Counter(value['disposition'] for _, value in self.receiver.store.records_after(0))
        return dict(task='P2-H5', status='COMPLETE_INGRESS' if self.complete else 'INCOMPLETE_INGRESS',
                    event_count=self.receiver.machine.event_count, dispositions=dict(sorted(counts.items())),
                    cutoff_policy='EXACT_MINUTE_END_ZERO_GRACE', original_cutoff_verified=False,
                    realtime_data_verified=False, real_broker_orders_enabled=False)


class ShadowEngine(ClosedLoopReplay):
    def __init__(self, config, profile, book, broker, receiver):
        self.receiver = receiver
        super().__init__(config, profile, book, broker, ingress=ReceiverView(receiver))

    def _after_replay(self):
        self.receiver.finish()

    def run(self, dataset, **kwargs):
        result = super().run(dataset, **kwargs)
        result.summary.update(task='P2-H5', runner_version='P2-H5:1',
                              incremental_event_input=True, recovery='DURABLE_RECEIVER_CURSOR_AND_MINUTE_PREFIX_REBUILD',
                              execution_availability='HISTORICAL_OHLC_MODEL_AS_OF_COMPLETED_MINUTE')
        return result


def run_incremental(source, events, journal, run_directory, config=None, profile=None, *,
                    queue_capacity=128, max_event_bytes=16384, stop_after_minutes=None,
                    output=None, protected_paths=(), control=None, hook=None):
    EventQueue(queue_capacity)  # Validate before touching runtime/journal paths.
    if stop_after_minutes is not None and (isinstance(stop_after_minutes, bool) or not isinstance(stop_after_minutes, int) or stop_after_minutes < 1):
        raise ValueError('invalid pause limit')
    config, profile = config or IntradayReplayConfig(), profile or HistoricalExecutionProfile()
    if config.opening_volume and source.provenance.get('feed') != 'sip' and source.provenance.get('source') != 'SYNTHETIC_DEMO':
        raise ValueError('opening volume source unsupported')
    directory, journal = Path(run_directory).resolve(), Path(journal).resolve()
    protected = {Path(p).resolve() for p in protected_paths} | {Path(events).resolve(), Path(str(events) + '.metadata.json').resolve()}
    writes = {(directory / name).resolve() for name in ('health.json', 'owner.sqlite3', 'stop.json')} | {journal, Path(str(journal) + '.lease.sqlite3')}
    if len(writes) != 5 or writes & protected or journal == directory or any(p.parent != directory for p in writes if p.name in ('health.json', 'owner.sqlite3', 'stop.json')):
        raise ValueError('runtime path conflict')
    if output is not None:
        report_path = Path(output).resolve()
        if report_path.exists() or any(report_path == p or report_path in p.parents for p in writes | protected) or directory in report_path.parents:
            raise ValueError('report path conflict')
    with SealedEventFile(events, source.provenance.get('csv_sha256'), max_event_bytes=max_event_bytes) as event_file:
        manifest = dict(manifest_for(source, config), contract_version='P2-H5:1', mode='INCREMENTAL_HISTORICAL_SHADOW',
            event_file_sha256=event_file.sha256, execution_profile=asdict(profile), queue_capacity=queue_capacity,
            max_event_bytes=max_event_bytes, recovery='DURABLE_RECEIVER_CURSOR_AND_MINUTE_PREFIX_REBUILD')
        identity = _hash(_json(manifest))
        with _owner(directory):
            prior = directory / 'health.json'
            if prior.exists():
                previous = json.loads(prior.read_text(encoding='utf-8'))
                if previous.get('manifest_sha256') != identity or previous.get('journal') != str(journal):
                    raise ValueError('run directory identity mismatch')
            state = dict(task='P2-H5', status='STARTING', attempt_id=uuid4().hex, manifest_sha256=identity,
                         journal=str(journal), started_at=_now(), updated_at=_now(), progress=None, account=None,
                         error_code=None, receipt=None, report_status='NOT_REQUESTED' if output is None else 'PENDING', real_broker_orders_enabled=False,
                         realtime_data_verified=False, algorithm_optimization_performed=False)
            last_write = 0.0

            def persist():
                nonlocal last_write
                state['updated_at'] = _now()
                _atomic_json(directory / 'health.json', state)
                last_write = time.monotonic()

            class Paused(Exception):
                pass

            try:
                persist()
                with ReceiverJournal(journal, manifest) as store:
                    receiver = IncrementalReceiver(store, source, event_file, queue_capacity, hook)
                    start_cursor = dict(receiver.cursor)
                    with TemporaryDirectory(prefix='.p2h5-rebuild-', dir=journal.parent) as temporary:
                        with OfflineOrderBook(Path(temporary) / 'orders.sqlite3', 'p2h5:' + identity, config.initial_cash) as book:
                            with ScriptedBroker(Path(temporary) / 'broker.sqlite3', 'p2h5:' + identity, config.initial_cash) as broker:
                                engine = ShadowEngine(config, profile, book, broker, receiver)
                                minutes, execution_events, prior_orders = 0, 0, {}
                                stopped, result = False, None

                                def observe(frame):
                                    nonlocal minutes, execution_events, prior_orders, stopped
                                    at = datetime.fromisoformat(frame['as_of'])
                                    new = store.sequence >= store.existing
                                    current = book.journal.state['orders']
                                    frame['orders'] = [deepcopy(value) for cid, value in current.items() if prior_orders.get(cid) != value]
                                    prior_orders = dict(current)
                                    frame['execution_events'] = deepcopy(engine.execution_events[execution_events:])
                                    execution_events = len(engine.execution_events)
                                    if frame['kind'] == 'MINUTE_COMPLETED':
                                        frame['market_input'] = receiver.packet
                                        for fill in frame['fills']:
                                            fill['market_input_as_of'] = frame['as_of']
                                    if new:
                                        event_file.assert_unchanged()
                                        frame['market_events'] = receiver.audit(at)
                                        frame['receiver_checkpoint'] = store.seal_checkpoint(receiver.checkpoint())
                                        if hook:
                                            hook('BEFORE_COMMIT', dict(frames=store.sequence + 1))
                                    else:
                                        original = store.stored_frame(frame['kind'], at)
                                        frame['market_events'] = original['market_events']
                                        frame['receiver_checkpoint'] = original['receiver_checkpoint']
                                        if frame['market_events']:
                                            # Prefix audit is already stored; new audit begins
                                            # after the corresponding persistent record sequence.
                                            receiver.last_audit += len(frame['market_events'])
                                    store.append(frame)  # Also commits receiver maps/cursor atomically.
                                    if hook:
                                        hook('AFTER_COMMIT', dict(frames=store.sequence))
                                    state['progress'] = dict(as_of=frame['as_of'], frames=store.sequence,
                                        verified_prefix_frames=store.verified, appended_frames=store.appended,
                                        source_cursor=frame['receiver_checkpoint']['source_cursor'],
                                        events_parsed_this_attempt=event_file.parsed)
                                    phase = 'RUNNING' if new else 'REBUILDING'
                                    changed = state['status'] != phase
                                    state['status'] = phase
                                    if frame.get('equity'):
                                        state['account'] = frame['equity'][-1]
                                    if changed or time.monotonic() - last_write >= 2:
                                        persist()
                                    request = directory / 'stop.json'
                                    stopped = (request.exists() and json.loads(request.read_text(encoding='utf-8')).get('attempt_id') == state['attempt_id']) or bool(control and control(dict(state['progress'])))
                                    if stopped:
                                        raise Paused()
                                    if new and frame['kind'] == 'MINUTE_COMPLETED':
                                        minutes += 1
                                        if stop_after_minutes is not None and minutes >= stop_after_minutes:
                                            raise Paused()

                                try:
                                    result = engine.run(source, observer=observe, minute_source=receiver)
                                    final_at = max(datetime.fromisoformat(result.daily[-1]['session_close']), receiver.machine.last_received_at or receiver.machine.watermark)
                                    final = dict(kind='RUN_COMPLETED', as_of=final_at.isoformat(), hypothetical=True, summary=result.summary)
                                    # Final completion includes any late post-session audit, but
                                    # does not revisit simulated execution after the closing frame.
                                    new = store.sequence >= store.existing
                                    if new:
                                        final['market_events'] = receiver.audit(final_at)
                                        final['receiver_checkpoint'] = store.seal_checkpoint(receiver.checkpoint())
                                    else:
                                        original = store.stored_frame('RUN_COMPLETED', final_at)
                                        final['market_events'] = original['market_events']
                                        final['receiver_checkpoint'] = original['receiver_checkpoint']
                                    event_file.assert_unchanged()
                                    store.append(final)
                                    if store.sequence < store.existing:
                                        raise ValueError('unexpected trailing shadow frames')
                                    status = 'COMPLETED' if result.summary['status'] == 'COMPLETE_REPLAY' else 'INCOMPLETE'
                                except Paused:
                                    status = 'STOPPED' if stopped else 'PAUSED'
                                queue = receiver.pump.queue if receiver.pump else None
                                receipt = dict(task='P2-H5', status=status, frames=store.sequence,
                                    verified_prefix_frames=store.verified, appended_frames=store.appended,
                                    journal_chain_sha256=store.chain, source_cursor=receiver.cursor,
                                    source_cursor_at_start=start_cursor, receiver_events=receiver.machine.event_count,
                                    events_parsed_this_attempt=event_file.parsed, queue_capacity=queue_capacity,
                                    queue_peak=queue.peak if queue else 0, backpressure_signals=queue.backpressure if queue else 0,
                                    source_eof=receiver.eof, real_broker_orders_enabled=False,
                                    realtime_data_verified=False, algorithm_optimization_performed=False)
                    state.update(status=status, receipt=receipt)
                    if state['progress'] is not None:
                        state['progress'].update(frames=store.sequence, verified_prefix_frames=store.verified,
                            appended_frames=store.appended, source_cursor=receiver.cursor)
                        if result is not None:
                            state['progress']['as_of'] = final_at.isoformat()
                    if result is not None and output is not None:
                        try:
                            write_report(result, output)
                            _atomic_json(Path(output) / 'incremental-receipt.json', receipt)
                            state['report_status'] = 'WRITTEN'
                        except Exception:
                            state['report_status'] = 'FAILED'
                            raise
                    elif output is not None:
                        state['report_status'] = 'DEFERRED'
                    persist()
                    return dict(state), result
            except BaseException:
                state.update(status='FAILED', error_code='INCREMENTAL_RUN_FAILED')
                try:
                    persist()
                except OSError:
                    pass
                raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('run')
    for name in ('input', 'events', 'journal', 'run-directory'):
        p.add_argument('--' + name, required=True)
    for name in ('config', 'profile', 'decision-start', 'output'):
        p.add_argument('--' + name)
    p.add_argument('--queue-capacity', type=int, default=128)
    p.add_argument('--max-event-bytes', type=int, default=16384)
    p.add_argument('--stop-after-minutes', type=int)
    for name in ('status', 'stop'):
        p = commands.add_parser(name)
        p.add_argument('--run-directory', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('status', 'stop'):
            value = health(args.run_directory) if args.command == 'status' else request_stop(args.run_directory)
            print(_json(value))
            return 0 if args.command == 'stop' or value['status'] in ('RUNNING', 'REBUILDING', 'STARTING', 'COMPLETED', 'PAUSED', 'STOPPED') else 4
        source = load_csv(args.input)
        profile = HistoricalExecutionProfile(**json.loads(Path(args.profile).read_text(encoding='utf-8'))) if args.profile else None
        stopped = False

        def stop(*_):
            nonlocal stopped
            stopped = True

        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            state, _ = run_incremental(source, args.events, args.journal, args.run_directory,
                read_config(args.config, args.decision_start), profile, queue_capacity=args.queue_capacity,
                max_event_bytes=args.max_event_bytes, stop_after_minutes=args.stop_after_minutes,
                output=args.output, protected_paths=[p for p in (args.input, args.input + '.metadata.json', args.input + '.raw.jsonl', args.config, args.profile) if p],
                control=lambda _: stopped)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        print(_json(state))
        return 0 if state['status'] == 'COMPLETED' else 3 if state['status'] in ('PAUSED', 'STOPPED') else 2
    except Exception:
        print(_json(dict(task='P2-H5', status='FAILED', error_code='INVALID_INPUT_OR_INCREMENTAL_RUNTIME', real_broker_orders_enabled=False)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
