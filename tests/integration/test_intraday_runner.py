from dataclasses import replace
from datetime import datetime, timedelta, timezone
import errno
import json
import os
import signal
import time
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from dx27.adapters.intraday import runner
from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.closed_loop import closed_loop_manifest, run_closed_loop
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.adapters.intraday.recorded_shadow import ShadowJournal
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


@pytest.fixture
def dataset(tmp_path):
    full = tmp_path / 'full.csv'
    create_demo(full)
    lines = full.read_text().splitlines()
    source = tmp_path / 'source.csv'
    source.write_text('\n'.join([lines[0]] + [line for line in lines[1:] if line.startswith('SPY,2025-11-28')]) + '\n')
    source.with_suffix('.csv.metadata.json').write_text(json.dumps({'source': 'SYNTHETIC_DEMO', 'symbols': ['SPY']}))
    return load_csv(source)


def paths(tmp_path):
    return tmp_path / 'journal.sqlite3', tmp_path / 'runtime'


def rows(path):
    with sqlite3.connect(path) as connection:
        return list(connection.execute('SELECT * FROM frames ORDER BY sequence'))


def test_preflight_is_read_only_and_detects_quality_without_claiming_profitability(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    report = runner.preflight(dataset, journal, runtime)
    assert report['status'] == 'READY' and report['sessions'] == 1
    assert report['regular_session_bars'] == 210 and report['data_quality_complete']
    assert not journal.exists() and not runtime.exists()
    missing = IntradayDataset(dataset.bars[1:], dataset.provenance)
    quality = runner.preflight(missing, journal, runtime)
    assert quality['missing_regular_bars'] == 1 and not quality['data_quality_complete']
    assert quality['real_broker_orders_enabled'] is False


def test_managed_pause_resume_rebuild_and_repeat_are_same_as_unsupervised(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    state, partial = runner.run_managed(dataset, journal, runtime, stop_after_minutes=40)
    assert state['status'] == 'PAUSED' and partial is None
    assert not runner.health(runtime)['owner_active']
    prefix = rows(journal)
    completed, result = runner.run_managed(dataset, journal, runtime)
    assert completed['status'] == 'COMPLETED'
    assert completed['receipt']['verified_prefix_frames'] == len(prefix)
    previous = rows(journal)
    _, control = run_closed_loop(dataset, tmp_path / 'control.sqlite3')
    assert result.summary == control.summary and result.fills == control.fills
    repeated, same = runner.run_managed(dataset, journal, runtime)
    assert repeated['receipt']['appended_frames'] == 0 and rows(journal) == previous
    assert same.summary == result.summary
    assert runner.health(runtime)['status'] == 'COMPLETED'
    assert completed['account']['reported_positions'] == completed['account']['broker_positions'] == {}
    assert completed['progress']['frames'] == completed['receipt']['frames']


def test_stop_request_is_honored_after_commit_and_stale_request_cannot_stop_new_attempt(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    requested = False

    def stop(progress):
        nonlocal requested
        assert rows(journal)[-1][0] == progress['frames']
        if not requested and progress['frames'] == 3:
            assert runner.health(runtime)['owner_active']
            response = runner.request_stop(runtime)
            assert response['status'] == 'STOP_REQUESTED'
            requested = True
        return False

    stopped, result = runner.run_managed(dataset, journal, runtime, control=stop)
    assert stopped['status'] == 'STOPPED' and result is None
    assert stopped['receipt']['frames'] == 4
    completed, _ = runner.run_managed(dataset, journal, runtime)
    assert completed['status'] == 'COMPLETED'
    assert completed['attempt_id'] != stopped['attempt_id']
    with pytest.raises(runner.RunnerError, match='NOT_RUNNING'):
        runner.request_stop(runtime)


def test_runner_and_journal_ownership_block_competing_writers_without_mutation(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    manifest = closed_loop_manifest(dataset, IntradayReplayConfig(), HistoricalExecutionProfile())
    with runner._owner(runtime):
        with pytest.raises(runner.RunnerError, match='RUNNER_BUSY'):
            runner.run_managed(dataset, journal, runtime)
        assert not (runtime / 'health.json').exists()
    with ShadowJournal(journal, manifest):
        before = journal.read_bytes()
        with pytest.raises(runner.RunnerError, match='JOURNAL_BUSY'):
            runner.preflight(dataset, journal, runtime)
        assert journal.read_bytes() == before


def test_modified_config_foreign_state_and_tampered_journal_fail_before_new_records(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    runner.run_managed(dataset, journal, runtime, stop_after_minutes=3)
    before = journal.read_bytes()
    health = (runtime / 'health.json').read_bytes()
    with pytest.raises(runner.RunnerError, match='MANIFEST_MISMATCH'):
        runner.run_managed(dataset, journal, runtime, profile=HistoricalExecutionProfile(fill_fraction=.5))
    assert journal.read_bytes() == before and (runtime / 'health.json').read_bytes() == health
    with pytest.raises(runner.RunnerError, match='RUN_DIRECTORY_MISMATCH'):
        runner.run_managed(dataset, tmp_path / 'another.sqlite3', runtime)
    assert not (tmp_path / 'another.sqlite3').exists()
    with sqlite3.connect(journal) as connection:
        connection.execute("UPDATE frames SET payload='{}' WHERE sequence=1")
    broken = journal.read_bytes()
    with pytest.raises(runner.RunnerError, match='INTEGRITY_FAILURE'):
        runner.run_managed(dataset, journal, runtime)
    assert journal.read_bytes() == broken


def test_path_aliases_and_existing_report_are_rejected(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    with pytest.raises(runner.RunnerError, match='PATH_CONFLICT'):
        runner.preflight(dataset, runtime / 'owner.sqlite3', runtime)
    with pytest.raises(runner.RunnerError, match='PATH_CONFLICT'):
        runner.preflight(dataset, journal, runtime, protected_paths=[journal])
    with pytest.raises(runner.RunnerError, match='REPORT_PATH_CONFLICT'):
        runner.preflight(dataset, journal, runtime, output=tmp_path)
    assert not runtime.exists() and not journal.exists()


def test_read_only_health_reports_crash_and_stall_without_signaling_pid(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    runner.run_managed(dataset, journal, runtime, stop_after_minutes=1)
    state = json.loads((runtime / 'health.json').read_text())
    state.update(status='RUNNING', updated_at=(datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat())
    (runtime / 'health.json').write_text(json.dumps(state))
    before = (runtime / 'health.json').read_bytes()
    assert runner.health(runtime)['status'] == 'INTERRUPTED'
    with runner._owner(runtime):
        assert runner.health(runtime)['status'] == 'STALLED'
        assert runner.health(runtime, stale_after_seconds=120)['status'] == 'RUNNING'
    assert (runtime / 'health.json').read_bytes() == before
    with pytest.raises(runner.RunnerError, match='STALENESS'):
        runner.health(runtime, stale_after_seconds=float('nan'))


def test_bounded_transient_failure_rebuilds_committed_prefix_without_duplicate_orders(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    failed = False

    def fault(progress):
        nonlocal failed
        if not failed and progress['frames'] == 5:
            failed = True
            raise OSError(errno.EIO, 'private failure details must not be logged')
        return False

    state, result = runner.run_managed(dataset, journal, runtime, max_restarts=1, control=fault)
    assert state['status'] == 'COMPLETED' and state['restarts'] == 1
    assert state['receipt']['verified_prefix_frames'] == 5
    _, reference = run_closed_loop(dataset, tmp_path / 'reference.sqlite3')
    assert result.fills == reference.fills and result.summary == reference.summary
    assert 'private failure' not in (runtime / 'health.json').read_text()


@pytest.mark.parametrize('failure', [ValueError('sensitive config text'), OSError(errno.ENOSPC, 'disk full')])
def test_validation_and_disk_full_fail_without_retry_or_sensitive_messages(dataset, tmp_path, failure):
    journal, runtime = paths(tmp_path)
    calls = 0

    def fault(progress):
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(type(failure)):
        runner.run_managed(dataset, journal, runtime, max_restarts=3, control=fault)
    state = runner.health(runtime)
    assert calls == 1 and state['restarts'] == 0 and state['status'] == 'FAILED'
    assert state['error_code'] == 'RUN_FAILED' and not state['owner_active']
    assert 'sensitive' not in (runtime / 'health.json').read_text()


def test_process_death_reports_interrupted_and_exactly_recovers_committed_journal(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    script = """
import os,sys
from dx27.adapters.intraday.runner import run_managed
from dx27.adapters.intraday.data import load_csv
run_managed(load_csv(sys.argv[1]),sys.argv[2],sys.argv[3],control=lambda p: os._exit(19) if p['frames']==10 else False)
"""
    process = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'source.csv'), str(journal), str(runtime)], timeout=45)
    assert process.returncode == 19
    assert runner.health(runtime)['status'] == 'INTERRUPTED'
    prefix = rows(journal)
    state, _ = runner.run_managed(dataset, journal, runtime)
    assert state['status'] == 'COMPLETED' and state['receipt']['verified_prefix_frames'] == 10
    assert rows(journal)[:10] == prefix


def test_unresolved_order_is_incomplete_without_automatic_restart(dataset, tmp_path):
    profile = HistoricalExecutionProfile(uncertain_every_nth_entry=1, uncertainty_mode='not_found')
    journal, runtime = paths(tmp_path)
    state, result = runner.run_managed(dataset, journal, runtime, profile=profile, max_restarts=3)
    assert state['status'] == 'INCOMPLETE' and state['restarts'] == 0
    assert result.summary['net_pnl'] is None
    assert runner.health(runtime)['status'] == 'INCOMPLETE'


def test_failed_health_write_cannot_leave_a_live_owner_or_report_success(dataset, tmp_path, monkeypatch):
    journal, runtime = paths(tmp_path)
    original = runner._atomic_json
    writes = 0

    def fault(path, value):
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError(errno.ENOSPC, 'private storage failure')
        original(path, value)

    monkeypatch.setattr(runner, '_atomic_json', fault)
    with pytest.raises(OSError):
        runner.run_managed(dataset, journal, runtime)
    assert runner.health(runtime)['status'] == 'INTERRUPTED'
    assert not runner.health(runtime)['owner_active']


def test_report_failure_preserves_completed_journal_and_is_explicit(dataset, tmp_path, monkeypatch):
    journal, runtime = paths(tmp_path)
    monkeypatch.setattr(runner, 'write_report', lambda *_: (_ for _ in ()).throw(OSError('secret detail')))
    with pytest.raises(runner.RunnerError, match='REPORT_WRITE_FAILED'):
        runner.run_managed(dataset, journal, runtime, output=tmp_path / 'report')
    state = runner.health(runtime)
    assert state['status'] == 'FAILED' and state['report_status'] == 'FAILED'
    assert state['receipt']['status'] == 'COMPLETE_CLOSED_LOOP'
    assert runner.preflight(dataset, journal, runtime)['journal_snapshot']['complete']
    assert 'secret detail' not in (runtime / 'health.json').read_text()


def test_cli_preflight_run_status_and_errors_need_no_credentials(dataset, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('APCA_API_KEY_ID', raising=False)
    monkeypatch.delenv('APCA_API_SECRET_KEY', raising=False)
    journal, runtime = paths(tmp_path)
    options = ['--input', str(tmp_path / 'source.csv'), '--journal', str(journal), '--run-directory', str(runtime)]
    assert runner.main(['preflight', *options]) == 0
    assert not runtime.exists()
    assert runner.main(['run', *options, '--stop-after-minutes', '2']) == 3
    assert runner.main(['status', '--run-directory', str(runtime)]) == 0
    assert runner.main(['stop', '--run-directory', str(runtime)]) == 1
    assert runner.main(['run', *options, '--output', str(tmp_path / 'report')]) == 0
    assert (tmp_path / 'report' / 'runner-receipt.json').exists()
    assert runner.main(['run', *options, '--max-restarts', '-1']) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(line['real_broker_orders_enabled'] is False for line in lines)


def test_invalid_input_and_source_gates_fail_before_runtime_files(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    config = IntradayReplayConfig(opening_volume=OpeningVolumeConfig(1, 1))
    unsupported = IntradayDataset(dataset.bars, {'source': 'LOCAL_CSV_UNVERIFIED'})
    with pytest.raises(runner.RunnerError, match='SOURCE_UNSUPPORTED'):
        runner.preflight(unsupported, journal, runtime, config)
    with pytest.raises(runner.RunnerError, match='NO_ACTIVE'):
        runner.preflight(dataset, journal, runtime, replace(IntradayReplayConfig(), decision_start=datetime(2030, 1, 1).date()))
    assert not runtime.exists() and not journal.exists()


def test_retry_budget_is_exhausted_without_unbounded_restart(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    calls = 0

    def fault(progress):
        nonlocal calls
        calls += 1
        raise OSError(errno.EIO, 'private error')

    with pytest.raises(OSError):
        runner.run_managed(dataset, journal, runtime, max_restarts=1, control=fault)
    state = runner.health(runtime)
    assert calls == 2 and state['restarts'] == 1 and state['status'] == 'FAILED'
    assert len(rows(journal)) == 1


@pytest.mark.skipif(os.name == 'nt', reason='Windows terminate bypasses Python SIGTERM handlers')
def test_cli_sigterm_stops_at_a_committed_boundary(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    ready = tmp_path / 'ready'
    script = """
import sys,time
from pathlib import Path
from dx27.adapters.intraday import runner
original=runner.run_managed
def controlled(*args, **kwargs):
    control=kwargs['control']
    def wait(progress):
        if progress['frames']==5:
            Path(sys.argv[4]).write_text('ready')
            for _ in range(100):
                if control(progress):
                    return True
                time.sleep(.05)
        return control(progress)
    kwargs['control']=wait
    return original(*args,**kwargs)
runner.run_managed=controlled
raise SystemExit(runner.main(['run','--input',sys.argv[1],'--journal',sys.argv[2],'--run-directory',sys.argv[3]]))
"""
    process = subprocess.Popen([sys.executable, '-c', script, str(tmp_path / 'source.csv'), str(journal), str(runtime), str(ready)], stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=20) == 3
        state = runner.health(runtime)
        assert state['status'] == 'STOPPED' and state['receipt']['frames'] == 5
        assert len(rows(journal)) == 5 and not state['owner_active']
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_death_during_sqlite_transaction_requires_read_only_preflight_then_locked_rollback(dataset, tmp_path):
    journal, runtime = paths(tmp_path)
    runner.run_managed(dataset, journal, runtime, stop_after_minutes=2)
    prefix = rows(journal)
    script = """
import os,sqlite3,sys
connection=sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA cache_size=1')
connection.execute('BEGIN IMMEDIATE')
connection.execute('UPDATE frames SET payload=? WHERE sequence=1',('x'*500000,))
os._exit(23)
"""
    process = subprocess.run([sys.executable, '-c', script, str(journal)], timeout=30)
    assert process.returncode == 23
    hot = Path(str(journal) + '-journal')
    assert hot.exists()
    before, rollback = journal.read_bytes(), hot.read_bytes()
    check = runner.preflight(dataset, journal, runtime)
    assert check['status'] == 'STORAGE_RECOVERY_REQUIRED'
    assert journal.read_bytes() == before and hot.read_bytes() == rollback
    state, result = runner.run_managed(dataset, journal, runtime)
    assert state['status'] == 'COMPLETED' and state['storage_recovery_performed']
    assert state['receipt']['verified_prefix_frames'] == 2
    assert rows(journal)[:2] == prefix
    assert not hot.exists()
