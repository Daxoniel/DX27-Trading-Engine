from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.closed_loop import run_closed_loop
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.market_ingress import historical_events, load_events, main, write_events
from dx27.adapters.intraday.runner import main as runner_main, run_managed
from dx27.application.market_ingress import compile_ingress
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.market_event import MarketEvent
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
    return load_csv(path)


def ordered(events):
    counters = {}
    output = []
    for event in sorted(events, key=lambda e: e.received_at):
        counters[event.connection] = counters.get(event.connection, 0) + 1
        output.append(replace(event, sequence=counters[event.connection]))
    return output


def compare_fills(left, right):
    for key in ('symbol', 'side', 'quantity', 'timestamp', 'decision_at', 'reason'):
        assert [row[key] for row in left.fills] == [row[key] for row in right.fills]
    assert left.summary['ending_cash'] == pytest.approx(right.summary['ending_cash'], abs=1e-6)


@pytest.mark.parametrize('volume', [None, OpeningVolumeConfig(1, 1)])
def test_canonical_event_control_matches_closed_loop_with_rvol_and_partial_fills(tmp_path, volume):
    path = tmp_path / 'full.csv'
    create_demo(path)
    source = load_csv(path)
    config = IntradayReplayConfig(opening_volume=volume)
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, exit_delay_minutes=1, fill_fraction=.5, entry_reservation_buffer_bps=100)
    ingress = compile_ingress(source, historical_events(source))
    _, original = run_closed_loop(source, tmp_path / 'original.sqlite3', config, profile)
    receipt, event_result = run_closed_loop(ingress.dataset, tmp_path / 'events.sqlite3', config, profile, ingress=ingress)
    assert ingress.complete and receipt['status'] == 'COMPLETE_CLOSED_LOOP'
    compare_fills(original, event_result)
    assert original.selections == event_result.selections
    assert event_result.summary['market_ingress']['original_cutoff_verified'] is False
    assert all(not row['ingress_recovering'] for row in event_result.equity)


def test_duplicate_delivery_and_duplicate_bar_never_double_volume_or_orders(source, tmp_path):
    events = list(historical_events(source))
    repeat = replace(events[20], received_at=events[22].received_at)
    semantic_repeat = replace(events[30], event_id='another-delivery-id')
    ingress = compile_ingress(source, ordered(events + [repeat, semantic_repeat]))
    counts = ingress.receipt()['dispositions']
    assert counts['DUPLICATE_DELIVERY'] == counts['DUPLICATE_BAR'] == 1
    assert len(ingress.dataset.bars) == len(source.bars) and ingress.complete
    _, original = run_closed_loop(source, tmp_path / 'original.sqlite3')
    _, result = run_closed_loop(ingress.dataset, tmp_path / 'duplicate.sqlite3', ingress=ingress)
    compare_fills(original, result)
    assert result.summary['order_count'] == original.summary['order_count']


def test_before_freeze_revision_is_atomic_but_post_cutoff_revision_preserves_old_bar(source):
    events = list(historical_events(source))
    original = events[20]
    revised = replace(original, event_id='revision-2', revision=2, bar=replace(original.bar, volume=original.bar.volume * 2))
    timely = compile_ingress(source, ordered(events + [revised]))
    assert timely.complete
    assert next(b for b in timely.dataset.bars if b.timestamp == original.bar.timestamp).volume == revised.bar.volume
    late = compile_ingress(source, ordered(events + [replace(revised, received_at=revised.received_at + timedelta(seconds=1))]))
    assert not late.complete
    assert next(b for b in late.dataset.bars if b.timestamp == original.bar.timestamp) == original.bar
    assert late.ready('SPY', original.received_at)
    assert not late.ready('SPY', original.received_at + timedelta(seconds=1))
    assert late.receipt()['dispositions']['POST_CUTOFF_REVISION'] == 1


def test_out_of_order_stale_revision_does_not_replace_newer_version(source):
    events = list(historical_events(source))
    original = events[20]
    revised = replace(original, event_id='revision-2', revision=2, bar=replace(original.bar, volume=100))
    stale = replace(original, event_id='stale-id', received_at=original.received_at + timedelta(seconds=1))
    variant = events[:20] + [revised] + events[21:] + [stale]
    ingress = compile_ingress(source, ordered(variant))
    assert ingress.complete and ingress.receipt()['dispositions']['STALE_REVISION'] == 1
    assert next(b for b in ingress.dataset.bars if b.timestamp == original.bar.timestamp).volume == 100


def test_revision_content_conflict_quarantines_symbol_and_suppresses_metrics(source, tmp_path):
    events = list(historical_events(source))
    original = events[40]
    conflict = replace(original, event_id='conflicting-version', bar=replace(original.bar, volume=1))
    ingress = compile_ingress(source, ordered(events + [conflict]))
    assert ingress.receipt()['dispositions']['REVISION_CONFLICT'] == 1
    assert not ingress.ready('SPY', original.received_at + timedelta(minutes=2))
    receipt, result = run_closed_loop(ingress.dataset, tmp_path / 'conflict.sqlite3', ingress=ingress)
    assert receipt['status'] == 'INCOMPLETE_CLOSED_LOOP'
    assert result.summary['net_pnl'] is None and result.summary['maximum_drawdown'] is None


def test_missing_then_late_bar_cannot_backfill_frozen_minute(source):
    events = list(historical_events(source))
    original = events[20]
    events[20] = replace(original, received_at=original.received_at + timedelta(seconds=1))
    ingress = compile_ingress(source, ordered(events))
    assert all(b.timestamp != original.bar.timestamp for b in ingress.dataset.bars)
    assert ingress.receipt()['dispositions']['MISSING_BAR'] == 1
    assert ingress.receipt()['dispositions']['LATE_BAR'] == 1
    assert not ingress.ready('SPY', original.received_at + timedelta(minutes=1))


def disconnected_trace(source, *, include_backfill=True):
    events = list(historical_events(source))
    start = events[40].bar.timestamp
    end = start + timedelta(minutes=3)
    initial = [event for event in events if event.received_at < start]
    source_name = source.provenance['source']
    disconnect = MarketEvent('lost', source_name, 'historical', 1, 'DISCONNECT', start, start)
    connect = MarketEvent('new-connection', source_name, 'reconnected', 1, 'CONNECT', end, end)
    backfill = [replace(event, connection='reconnected', received_at=end) for event in events if event.kind == 'BAR' and start <= event.received_at <= end]
    if not include_backfill:
        backfill = backfill[1:]
    sync = MarketEvent('sync', source_name, 'reconnected', 1, 'SYNC', end, end, through=end)
    tail = [replace(event, connection='reconnected') for event in events if event.received_at > end]
    return ordered(initial + [disconnect, connect] + backfill + [sync] + tail), start, end


def test_reconnect_requires_contiguous_backfill_before_forward_admission(source, tmp_path):
    events, start, end = disconnected_trace(source)
    ingress = compile_ingress(source, events)
    assert not ingress.ready('SPY', start + timedelta(minutes=1))
    assert ingress.ready('SPY', end)
    assert ingress.receipt()['dispositions']['SYNCHRONIZED'] == 1
    assert not ingress.complete  # Historical gaps and outage evidence remain.
    assert all(b.timestamp not in (start, start + timedelta(minutes=1)) for b in ingress.dataset.bars)
    receipt, result = run_closed_loop(ingress.dataset, tmp_path / 'reconnect.sqlite3', ingress=ingress)
    assert receipt['status'] == 'INCOMPLETE_CLOSED_LOOP'
    assert not any(start <= datetime.fromisoformat(f['timestamp']) < end for f in result.fills if f['side'] == 'buy')


def test_incomplete_sync_or_sequence_gap_keeps_admission_paused(source):
    events, start, end = disconnected_trace(source, include_backfill=False)
    incomplete = compile_ingress(source, events)
    assert incomplete.receipt()['dispositions']['SYNC_INCOMPLETE'] == 1
    assert not incomplete.ready('SPY', end + timedelta(minutes=5))
    base = list(historical_events(source))
    broken = [replace(e, sequence=e.sequence + 1) if i >= 20 else e for i, e in enumerate(base)]
    gap = compile_ingress(source, broken)
    assert gap.receipt()['dispositions']['SEQUENCE_GAP'] == 1 and not gap.ready('SPY', base[22].received_at)


@pytest.mark.parametrize('failure', ['identity', 'sequence', 'clock', 'source'])
def test_ambiguous_identity_receipt_order_and_source_fail_closed(source, failure):
    events = list(historical_events(source))
    if failure == 'identity':
        events.insert(20, replace(events[20], bar=replace(events[20].bar, volume=1)))
        events = ordered(events)
    elif failure == 'sequence':
        events[20] = replace(events[20], sequence=events[19].sequence)
    elif failure == 'clock':
        events[20], events[21] = events[21], events[20]
    else:
        events[20] = replace(events[20], source='IEX_OTHER_SOURCE')
    with pytest.raises(ValueError):
        compile_ingress(source, events)


@pytest.mark.parametrize('change', [dict(revision=0), dict(sequence=True), dict(kind='TICK'), dict(connection='bad connection')])
def test_invalid_event_contracts_are_rejected(source, change):
    event = next(e for e in historical_events(source) if e.kind == 'BAR')
    with pytest.raises(ValueError):
        replace(event, **change)
    with pytest.raises(ValueError):
        replace(event, available_at=event.bar.timestamp)
    with pytest.raises(ValueError):
        replace(event, received_at=event.available_at - timedelta(seconds=1))


def test_future_events_do_not_change_earlier_frozen_frames_or_admission(source, tmp_path):
    events = list(historical_events(source))
    cutoff = events[80].received_at
    variant = [replace(e, bar=replace(e.bar, volume=e.bar.volume * 10)) if e.bar and e.received_at >= cutoff else e for e in events]
    recorded = []
    for i, stream in enumerate((events, variant)):
        ingress = compile_ingress(source, stream)
        journal = tmp_path / f'{i}.sqlite3'
        run_closed_loop(ingress.dataset, journal, ingress=ingress)
        with sqlite3.connect(journal) as connection:
            rows = [json.loads(row[0]) for row in connection.execute('SELECT payload FROM frames')]
        for frame in rows:
            for row in frame.get('fills', []):
                row.pop('client_order_id', None)
            for row in frame.get('orders', []):
                row.pop('client_order_id', None)
        recorded.append([frame for frame in rows if frame['as_of'] < cutoff.isoformat()])
    # Order namespaces depend on the full immutable trace. Compare strategy
    # records, excluding stable IDs that intentionally differ across manifests.
    for left, right in zip(*recorded):
        for field in ('equity', 'decisions', 'fills', 'trades', 'market_events'):
            assert left[field] == right[field]


def test_resume_repeats_event_audit_once_and_rejects_changed_receipts(source, tmp_path):
    events = list(historical_events(source))
    ingress = compile_ingress(source, events)
    journal, runtime = tmp_path / 'journal.sqlite3', tmp_path / 'runtime'
    paused, _ = run_managed(ingress.dataset, journal, runtime, ingress=ingress, stop_after_minutes=12)
    assert paused['status'] == 'PAUSED'
    completed, _ = run_managed(ingress.dataset, journal, runtime, ingress=ingress)
    assert completed['receipt']['verified_prefix_frames'] == 12
    repeat, _ = run_managed(ingress.dataset, journal, runtime, ingress=ingress)
    assert repeat['receipt']['appended_frames'] == 0
    changed = list(events)
    changed[20] = replace(changed[20], received_at=changed[20].received_at + timedelta(seconds=1))
    variant = compile_ingress(source, ordered(changed))
    with pytest.raises(RuntimeError, match='MISMATCH'):
        run_managed(variant.dataset, journal, runtime, ingress=variant)
    with pytest.raises(ValueError, match='requires its ingress gates'):
        run_closed_loop(ingress.dataset, tmp_path / 'unsafe.sqlite3')


def test_revision_after_last_close_is_visible_only_in_final_audit(source, tmp_path):
    events = list(historical_events(source))
    last = events[-1]
    revision = replace(last, event_id='after-close-correction', revision=2, received_at=last.received_at + timedelta(seconds=1), bar=replace(last.bar, volume=1))
    ingress = compile_ingress(source, ordered(events + [revision]))
    receipt, result = run_closed_loop(ingress.dataset, tmp_path / 'late-close.sqlite3', ingress=ingress)
    assert receipt['status'] == 'INCOMPLETE_CLOSED_LOOP' and result.summary['net_pnl'] is None
    with sqlite3.connect(tmp_path / 'late-close.sqlite3') as connection:
        frames = [json.loads(row[0]) for row in connection.execute('SELECT payload FROM frames ORDER BY sequence')]
    assert frames[-1]['as_of'] == revision.received_at.isoformat()
    assert frames[-1]['market_events'][0]['disposition'] == 'POST_CUTOFF_REVISION'
    assert not any(r['event_id'] == revision.event_id for frame in frames[:-1] for r in frame['market_events'])


def test_event_file_seals_cli_and_runtime_need_no_credentials(source, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('APCA_API_KEY_ID', raising=False)
    monkeypatch.delenv('APCA_API_SECRET_KEY', raising=False)
    path = tmp_path / 'events.jsonl'
    assert main(['convert', '--input', str(tmp_path / 'source.csv'), '--output', str(path)]) == 0
    assert main(['inspect', '--input', str(tmp_path / 'source.csv'), '--events', str(path)]) == 0
    original = compile_ingress(source, historical_events(source))
    loaded = compile_ingress(source, load_events(path, source))
    assert loaded.receipt() == original.receipt()
    options = ['--input', str(tmp_path / 'source.csv'), '--events', str(path), '--journal', str(tmp_path / 'cli.sqlite3'), '--run-directory', str(tmp_path / 'cli-runtime')]
    assert runner_main(['preflight', *options]) == 0
    assert runner_main(['run', *options]) == 0
    assert not any(line.get('real_broker_orders_enabled') for line in [json.loads(line) for line in capsys.readouterr().out.splitlines()])
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='seal'):
        load_events(path, source)


def test_disconnect_cancels_unfilled_entry_tranches_without_inventing_inventory(source, tmp_path):
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, fill_fraction=.5, entry_reservation_buffer_bps=100)
    _, control = run_closed_loop(source, tmp_path / 'reference.sqlite3', profile=profile)
    first = next(f for f in control.fills if f['side'] == 'buy')
    start = datetime.fromisoformat(first['timestamp']) + timedelta(minutes=1, seconds=1)
    end = (start + timedelta(minutes=3)).replace(second=0, microsecond=0)
    events = list(historical_events(source))
    name = source.provenance['source']
    initial = [e for e in events if e.received_at < start]
    disconnect = MarketEvent('lost-during-entry', name, 'historical', 1, 'DISCONNECT', start, start)
    connect = MarketEvent('resume-after-entry', name, 'reconnected', 1, 'CONNECT', end, end)
    backfill = [replace(e, connection='reconnected', received_at=end) for e in events if e.kind == 'BAR' and start <= e.received_at <= end]
    sync = MarketEvent('entry-sync', name, 'reconnected', 1, 'SYNC', end, end, through=end)
    tail = [replace(e, connection='reconnected') for e in events if e.received_at > end]
    ingress = compile_ingress(source, ordered(initial + [disconnect, connect] + backfill + [sync] + tail))
    _, result = run_closed_loop(ingress.dataset, tmp_path / 'interrupted.sqlite3', profile=profile, ingress=ingress)
    buy = next(f for f in result.fills if f['side'] == 'buy')
    assert buy['quantity'] == first['quantity']
    assert sum(f['quantity'] for f in result.fills if f['client_order_id'] == buy['client_order_id']) == buy['quantity']
    assert result.summary['broker_ending_positions'] == {} and result.summary['net_pnl'] is None


def test_post_signal_revision_blocks_only_later_pending_entry(source, tmp_path):
    _, original = run_closed_loop(source, tmp_path / 'original.sqlite3')
    first = next(f for f in original.fills if f['side'] == 'buy')
    decision_at = datetime.fromisoformat(first['decision_at'])
    events = list(historical_events(source))
    bar = next(e for e in events if e.bar and e.bar.timestamp + timedelta(minutes=1) == decision_at)
    correction = replace(bar, event_id='revision-after-signal', revision=2,
        received_at=decision_at + timedelta(seconds=1), bar=replace(bar.bar, volume=1))
    ingress = compile_ingress(source, ordered(events + [correction]))
    _, result = run_closed_loop(ingress.dataset, tmp_path / 'gated.sqlite3', ingress=ingress)
    assert any(row['decision_at'] == decision_at.isoformat() and row['action'] == 'QUEUE_LONG' for row in result.decisions)
    assert any(row['reason'] == 'market_ingress_gate' and row['decision_at'] > correction.received_at.isoformat() for row in result.decisions)
    assert result.summary['order_count'] == 0 and not result.fills


def test_equivalent_timezone_delivery_clocks_are_one_event_identity(source):
    events = list(historical_events(source))
    original = events[20]
    offset = timezone(timedelta(hours=2))
    duplicate = replace(original, available_at=original.available_at.astimezone(offset),
        received_at=original.received_at.astimezone(offset), bar=replace(original.bar, timestamp=original.bar.timestamp.astimezone(offset)))
    ingress = compile_ingress(source, ordered(events + [duplicate]))
    assert ingress.complete and ingress.receipt()['dispositions']['DUPLICATE_DELIVERY'] == 1
    assert ingress.dataset.bars == source.bars


def test_entire_missing_final_session_stays_in_calendar_and_daily_quality(tmp_path):
    path = tmp_path / 'full.csv'
    create_demo(path)
    source = load_csv(path)
    events = list(historical_events(source))
    first_date = events[0].received_at.date()
    retained = [e for e in events if e.received_at.date() == first_date]
    ingress = compile_ingress(source, retained)
    assert not ingress.complete
    assert ingress.receipt()['dispositions']['MISSING_BAR'] == 210 * 3
    _, result = run_closed_loop(ingress.dataset, tmp_path / 'missing-session.sqlite3', ingress=ingress)
    assert result.summary['sessions'] == 2
    assert result.daily[-1]['session'] == '2025-11-28' and not result.daily[-1]['data_complete']
    assert result.summary['net_pnl'] is None
