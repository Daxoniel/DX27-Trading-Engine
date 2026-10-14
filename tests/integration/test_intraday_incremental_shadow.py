from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.closed_loop import run_closed_loop
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.event_stream import EventQueue, SealedEventFile
from dx27.adapters.intraday.incremental_shadow import main, run_incremental
from dx27.adapters.intraday.market_ingress import historical_events, write_events
from dx27.adapters.intraday.recorded_shadow import _json
from dx27.adapters.intraday.runner import _owner, health, request_stop
from dx27.application.market_ingress import compile_ingress
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


@pytest.fixture
def source(tmp_path):
    full = tmp_path / 'full.csv'
    create_demo(full)
    lines = full.read_text().splitlines()
    path = tmp_path / 'source.csv'
    path.write_text('\n'.join([lines[0]] + [line for line in lines[1:] if line.startswith('SPY,2025-11-28')]) + '\n')
    path.with_suffix('.csv.metadata.json').write_text(json.dumps({'source': 'SYNTHETIC_DEMO', 'symbols': ['SPY']}))
    source = load_csv(path)
    write_events(source, tmp_path / 'events.jsonl')
    return source


def run(source, root, events=None, **kwargs):
    return run_incremental(source, events or root.parent / 'events.jsonl', root / 'shadow.sqlite3', root / 'runtime', **kwargs)


def frames(path):
    with sqlite3.connect(path) as connection:
        return list(connection.execute('SELECT payload FROM frames ORDER BY sequence'))


def equivalent(left, right):
    for key in ('symbol', 'side', 'quantity', 'timestamp', 'decision_at', 'reason', 'commission', 'cash_delta'):
        assert [f[key] for f in left.fills] == [f[key] for f in right.fills]
    assert left.summary['ending_cash'] == right.summary['ending_cash']
    assert left.selections == right.selections


@pytest.mark.parametrize('volume', [None, OpeningVolumeConfig(1, 1)])
def test_streamed_rvol_partial_fill_path_matches_frozen_control_without_compiling_trace(tmp_path, volume, monkeypatch):
    source_path = tmp_path / 'full.csv'
    create_demo(source_path)
    source = load_csv(source_path)
    write_events(source, tmp_path / 'events.jsonl')
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, exit_delay_minutes=1, fill_fraction=.5, entry_reservation_buffer_bps=100)
    config = IntradayReplayConfig(opening_volume=volume)
    frozen = compile_ingress(source, historical_events(source))
    _, reference = run_closed_loop(frozen.dataset, tmp_path / 'reference.sqlite3', config, profile, ingress=frozen)
    import dx27.application.market_ingress as ingress_module
    monkeypatch.setattr(ingress_module, 'compile_ingress', lambda *_: (_ for _ in ()).throw(AssertionError('must not compile full trace')))
    state, result = run(source, tmp_path / 'stream', profile=profile, config=config, queue_capacity=2)
    assert state['status'] == 'COMPLETED'
    equivalent(result, reference)
    assert state['receipt']['queue_peak'] <= 2 and state['receipt']['backpressure_signals'] > 0
    assert state['receipt']['receiver_events'] == 1801 and state['receipt']['source_eof']
    assert result.summary['incremental_event_input']


def test_resume_reads_only_source_suffix_and_exactly_matches_uninterrupted_journal(source, tmp_path, monkeypatch):
    root = tmp_path / 'resumed'
    paused, _ = run(source, root, queue_capacity=4, stop_after_minutes=12)
    cursor = paused['receipt']['source_cursor']
    assert cursor['line_number'] == 13
    committed = frames(root / 'shadow.sqlite3')
    original = SealedEventFile.next_item

    def suffix_only(self):
        item = original(self)
        if item:
            assert item.line_number > cursor['line_number']
        return item

    with monkeypatch.context() as patch:
        patch.setattr(SealedEventFile, 'next_item', suffix_only)
        completed, result = run(source, root, queue_capacity=4)
    assert completed['receipt']['source_cursor_at_start'] == cursor
    assert completed['receipt']['events_parsed_this_attempt'] == 211 - 13
    assert frames(root / 'shadow.sqlite3')[:12] == committed
    uninterrupted, same = run(source, tmp_path / 'fresh', queue_capacity=4)
    assert frames(root / 'shadow.sqlite3') == frames(tmp_path / 'fresh/shadow.sqlite3')
    assert asdict(result) == asdict(same)
    repeated, _ = run(source, root, queue_capacity=4)
    assert repeated['receipt']['events_parsed_this_attempt'] == repeated['receipt']['appended_frames'] == 0
    assert completed['receipt']['journal_chain_sha256'] == repeated['receipt']['journal_chain_sha256']


def test_queue_rejection_retains_item_and_capacity_one_handles_large_same_clock_group(source, tmp_path):
    queue = EventQueue(1)
    assert queue.offer('first') and not queue.offer('second')
    assert queue.pop() == 'first' and queue.offer('second') and queue.pop() == 'second'
    events = list(historical_events(source))
    first = events[1]
    duplicates = [replace(first, event_id=f'duplicate-{i}') for i in range(100)]
    stream = events[:2] + duplicates + events[2:]
    stream = [replace(event, sequence=index + 1) for index, event in enumerate(stream)]
    path = tmp_path / 'burst.jsonl'
    path.write_text('\n'.join(_json(asdict(event)) for event in stream) + '\n')
    state, result = run(source, tmp_path / 'burst', path, queue_capacity=1)
    assert state['status'] == 'COMPLETED' and state['receipt']['queue_peak'] == 1
    assert result.summary['market_ingress']['dispositions']['DUPLICATE_BAR'] == 100
    _, reference = run(source, tmp_path / 'control', queue_capacity=1)
    equivalent(result, reference)


@pytest.mark.parametrize('stage', ['EVENT_CONSUMED', 'BEFORE_COMMIT'])
def test_failure_inside_receiver_and_shadow_transaction_rolls_back_to_previous_cursor(source, tmp_path, stage):
    root = tmp_path / stage

    def failure(name, data):
        if name == stage and data.get('events', data.get('frames', 0)) == 10:
            raise OSError('private exception details')

    with pytest.raises(OSError):
        run(source, root, queue_capacity=2, hook=failure)
    status = health(root / 'runtime')
    assert status['status'] == 'FAILED' and not status['owner_active']
    with sqlite3.connect(root / 'shadow.sqlite3') as connection:
        count = connection.execute('SELECT count(*) FROM frames').fetchone()[0]
        checkpoint = json.loads(connection.execute("SELECT value FROM metadata WHERE key='receiver_checkpoint'").fetchone()[0])
    assert count in (8, 9)
    assert checkpoint['source_cursor']['line_number'] == count + 1
    resumed, result = run(source, root, queue_capacity=2)
    _, reference = run(source, tmp_path / ('reference-' + stage), queue_capacity=2)
    equivalent(result, reference)
    assert resumed['receipt']['verified_prefix_frames'] == count
    assert 'private exception' not in (root / 'runtime/health.json').read_text()


def test_process_death_mid_transaction_releases_both_leases_and_restores_cursor(source, tmp_path):
    root = tmp_path / 'crash'
    script = """
import os,sys
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.incremental_shadow import run_incremental
def hook(stage,data):
 if stage=='EVENT_CONSUMED' and data['events']==11: os._exit(27)
run_incremental(load_csv(sys.argv[1]),sys.argv[2],sys.argv[3],sys.argv[4],queue_capacity=2,hook=hook)
"""
    process = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'source.csv'), str(tmp_path / 'events.jsonl'), str(root / 'shadow.sqlite3'), str(root / 'runtime')], timeout=45)
    assert process.returncode == 27 and health(root / 'runtime')['status'] == 'INTERRUPTED'
    state, result = run(source, root, queue_capacity=2)
    assert state['status'] == 'COMPLETED' and state['receipt']['source_cursor_at_start']['line_number'] == 10
    _, reference = run(source, tmp_path / 'fresh', queue_capacity=2)
    equivalent(result, reference)


@pytest.mark.parametrize('table', ['receiver_rows', 'metadata'])
def test_receiver_map_or_checkpoint_tampering_is_refused_before_new_frames(source, tmp_path, table):
    root = tmp_path / table
    run(source, root, stop_after_minutes=5)
    with sqlite3.connect(root / 'shadow.sqlite3') as connection:
        if table == 'receiver_rows':
            connection.execute("UPDATE receiver_rows SET value='\"wrong\"' WHERE space='identities' AND key=(SELECT key FROM receiver_rows WHERE space='identities' LIMIT 1)")
        else:
            value = json.loads(connection.execute("SELECT value FROM metadata WHERE key='receiver_checkpoint'").fetchone()[0])
            value['source_cursor']['byte_offset'] = 0
            connection.execute("UPDATE metadata SET value=? WHERE key='receiver_checkpoint'", (_json(value),))
    previous = frames(root / 'shadow.sqlite3')
    with pytest.raises(ValueError, match='integrity|checkpoint'):
        run(source, root)
    assert frames(root / 'shadow.sqlite3') == previous


def test_changed_source_content_and_foreign_journal_never_overwrite_state(source, tmp_path):
    root = tmp_path / 'root'
    run(source, root, stop_after_minutes=2)
    previous = frames(root / 'shadow.sqlite3')
    path = tmp_path / 'events.jsonl'
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='seal'):
        run(source, root)
    assert frames(root / 'shadow.sqlite3') == previous
    from dx27.adapters.intraday.order_book import OfflineOrderBook
    foreign = tmp_path / 'foreign.sqlite3'
    with OfflineOrderBook(foreign, 'foreign', 100000):
        pass
    old = foreign.read_bytes()
    with pytest.raises(ValueError):
        run_incremental(source, path, foreign, tmp_path / 'foreign-runtime')
    assert foreign.read_bytes() == old


def test_source_modified_during_reception_stops_before_next_minute_commit(source, tmp_path):
    events = tmp_path / 'events.jsonl'
    root = tmp_path / 'mutation'

    def change(stage, data):
        if stage == 'AFTER_COMMIT' and data['frames'] == 5:
            with events.open('ab') as stream:
                stream.write(b'\n')

    with pytest.raises(ValueError, match='changed'):
        run(source, root, queue_capacity=2, hook=change)
    assert len(frames(root / 'shadow.sqlite3')) == 5


@pytest.mark.parametrize('kind', ['oversize', 'duplicate_json', 'clock_regression'])
def test_bounded_reader_and_event_clock_validation_fail_closed(source, tmp_path, kind):
    path = tmp_path / (kind + '.jsonl')
    if kind == 'oversize':
        path.write_text(' ' * 600 + '\n')
    elif kind == 'duplicate_json':
        path.write_text('{"event_id":"a","event_id":"b"}\n')
    else:
        events = list(historical_events(source))
        events[10], events[11] = events[11], events[10]
        path.write_text('\n'.join(_json(asdict(event)) for event in events) + '\n')
    with pytest.raises(ValueError):
        run(source, tmp_path / kind, path, max_event_bytes=512)
    assert health(tmp_path / kind / 'runtime')['status'] == 'FAILED'


def test_post_session_revision_is_final_audit_and_suppresses_performance(source, tmp_path):
    events = list(historical_events(source))
    last = events[-1]
    from datetime import timedelta
    events.append(replace(last, event_id='late-correction', sequence=last.sequence + 1, revision=2,
        received_at=last.received_at + timedelta(seconds=1), bar=replace(last.bar, volume=1)))
    path = tmp_path / 'late.jsonl'
    path.write_text('\n'.join(_json(asdict(event)) for event in events) + '\n')
    state, result = run(source, tmp_path / 'late', path)
    assert state['status'] == 'INCOMPLETE' and result.summary['net_pnl'] is None
    rows = [json.loads(row[0]) for row in frames(tmp_path / 'late/shadow.sqlite3')]
    assert rows[-1]['market_events'][0]['disposition'] == 'POST_CUTOFF_REVISION'
    assert rows[-1]['as_of'] == events[-1].received_at.isoformat()
    assert state['progress']['as_of'] == rows[-1]['as_of']
    assert not any(r['event_id'] == 'late-correction' for frame in rows[:-1] for r in frame['market_events'])


def test_cooperative_stop_target_is_attempt_specific_and_writer_lock_blocks_duplicate_runner(source, tmp_path):
    root = tmp_path / 'stop'
    requested = False

    def control(progress):
        nonlocal requested
        if not requested:
            request_stop(root / 'runtime')
            requested = True
        return False

    stopped, _ = run(source, root, control=control)
    assert stopped['status'] == 'STOPPED'
    completed, _ = run(source, root)
    assert completed['status'] == 'COMPLETED' and completed['attempt_id'] != stopped['attempt_id']
    with _owner(root / 'runtime'):
        with pytest.raises(RuntimeError, match='BUSY'):
            run(source, root)


def test_cli_and_reports_work_without_credentials(source, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('APCA_API_KEY_ID', raising=False)
    monkeypatch.delenv('APCA_API_SECRET_KEY', raising=False)
    options = ['--input', str(tmp_path / 'source.csv'), '--events', str(tmp_path / 'events.jsonl'), '--journal', str(tmp_path / 'cli.sqlite3'), '--run-directory', str(tmp_path / 'cli-runtime'), '--queue-capacity', '2']
    assert main(['run', *options, '--stop-after-minutes', '2']) == 3
    assert main(['run', *options, '--output', str(tmp_path / 'report')]) == 0
    assert main(['status', '--run-directory', str(tmp_path / 'cli-runtime')]) == 0
    assert (tmp_path / 'report/incremental-receipt.json').exists()
    assert all(value['real_broker_orders_enabled'] is False for value in [json.loads(line) for line in capsys.readouterr().out.splitlines()])


@pytest.mark.parametrize('kwargs', [dict(queue_capacity=0), dict(queue_capacity=True), dict(max_event_bytes=10), dict(stop_after_minutes=0)])
def test_invalid_buffer_limits_are_rejected_before_journal_creation(source, tmp_path, kwargs):
    with pytest.raises(ValueError):
        run(source, tmp_path / 'invalid', **kwargs)
    assert not (tmp_path / 'invalid/shadow.sqlite3').exists()


@pytest.mark.parametrize('fault', ['late', 'conflict', 'reconnect'])
def test_durable_policy_faults_match_compiled_control_across_restart(source, tmp_path, fault):
    from datetime import timedelta
    from dx27.domains.intraday.market_event import MarketEvent
    events = list(historical_events(source))
    original = events[20]
    if fault == 'late':
        events[20] = replace(original, received_at=original.received_at + timedelta(seconds=1))
    elif fault == 'conflict':
        events.append(replace(original, event_id='conflict-version', bar=replace(original.bar, volume=1)))
    else:
        start, end = original.bar.timestamp, original.bar.timestamp + timedelta(minutes=3)
        initial = [e for e in events if e.received_at < start]
        name = source.provenance['source']
        disconnected = MarketEvent('disconnected', name, 'historical', 1, 'DISCONNECT', start, start)
        connected = MarketEvent('reconnected', name, 'new', 1, 'CONNECT', end, end)
        backfill = [replace(e, connection='new', received_at=end) for e in events if e.kind == 'BAR' and start <= e.received_at <= end]
        synced = MarketEvent('sync', name, 'new', 1, 'SYNC', end, end, through=end)
        tail = [replace(e, connection='new') for e in events if e.received_at > end]
        events = initial + [disconnected, connected] + backfill + [synced] + tail
    counters, ordered = {}, []
    for event in sorted(events, key=lambda e: e.received_at):
        counters[event.connection] = counters.get(event.connection, 0) + 1
        ordered.append(replace(event, sequence=counters[event.connection]))
    path = tmp_path / (fault + '.jsonl')
    path.write_text('\n'.join(_json(asdict(e)) for e in ordered) + '\n')
    frozen = compile_ingress(source, ordered)
    _, control = run_closed_loop(frozen.dataset, tmp_path / (fault + '-control.sqlite3'), ingress=frozen)
    root = tmp_path / fault
    run(source, root, path, queue_capacity=2, stop_after_minutes=22)
    state, result = run(source, root, path, queue_capacity=2)
    assert state['status'] == 'INCOMPLETE' and result.summary['net_pnl'] is None
    equivalent(result, control)
    assert result.summary['market_ingress']['dispositions'] == frozen.receipt()['dispositions']
    repeated, _ = run(source, root, path, queue_capacity=2)
    assert repeated['receipt']['appended_frames'] == 0 and repeated['receipt']['events_parsed_this_attempt'] == 0


def test_report_failure_retains_complete_execution_receipt(source, tmp_path, monkeypatch):
    import dx27.adapters.intraday.incremental_shadow as module
    monkeypatch.setattr(module, 'write_report', lambda *_: (_ for _ in ()).throw(OSError('private report failure')))
    root = tmp_path / 'failed-report'
    with pytest.raises(OSError):
        run(source, root, output=tmp_path / 'report')
    state = health(root / 'runtime')
    assert state['status'] == 'FAILED' and state['report_status'] == 'FAILED'
    assert state['receipt']['status'] == 'COMPLETED'
    assert 'private report failure' not in (root / 'runtime/health.json').read_text()
