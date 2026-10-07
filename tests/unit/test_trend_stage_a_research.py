"""Offline orchestration checks; no Yahoo or saved real artifacts accessed."""
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / 'runners/standalone'
sys.path.insert(0, str(RUNNERS))
try:
    spec = importlib.util.spec_from_file_location('stage_a_research', RUNNERS / 'trend_stage_a_research.py')
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
finally:
    sys.path.pop(0)


@pytest.fixture
def acquisition():
    dates = pd.bdate_range('2003-01-01', periods=256).strftime('%Y-%m-%d').tolist()
    dates += ['2005-01-03', '2019-12-31', '2020-01-02', '2026-09-30']
    rows = []
    for symbol in r.yahoo.STAGE_A_SYMBOLS:
        for date in dates:
            rows.append(dict(symbol=symbol, date=date, open=100., high=101., low=99., close=100., volume=0))
    frame = pd.DataFrame(rows)
    coverage = r.yahoo.validate_data(frame)
    normalization = dict(classification='DX27_PROVIDER_BOUNDARY_NORMALIZATION', relative_tolerance=1e-12,
                         absolute_tolerance=1e-12, high_corrections_total=0, low_corrections_total=0,
                         symbols={s:dict(high_corrections=0, low_corrections=0) for s in r.yahoo.STAGE_A_SYMBOLS})
    return frame, coverage, normalization


def mock_context(monkeypatch):
    context = dict(execution_commit='a' * 40, python_version='3.12', yfinance_version='1.7.0',
                   pandas_version='3.0.6', numpy_version='2.5.3')
    monkeypatch.setattr(r, 'execution_context', lambda: context)
    return context


def test_canonical_hash_order_invariant_and_value_sensitive(acquisition):
    frame, _, _ = acquisition
    assert r.canonical_csv(frame) == r.canonical_csv(frame.sample(frac=1, random_state=7))
    assert r.canonical_csv(frame).splitlines()[0] == b'symbol,date,open,high,low,close,volume'
    altered = frame.copy()
    altered.loc[0, 'volume'] = 1
    assert r.digest(r.canonical_csv(frame)) != r.digest(r.canonical_csv(altered))


def test_freeze_auditable_and_exclusive(acquisition, tmp_path):
    context = dict(execution_commit='b' * 40)
    source, manifest = r.freeze_data(*acquisition, context, tmp_path, '2026-10-07T00:00:00Z')
    assert manifest['combined_dataset_sha256'] == r.digest(source.read_bytes())
    assert len(manifest['per_symbol_metadata']) == 13
    for symbol, metadata in manifest['per_symbol_metadata'].items():
        assert metadata['sha256'] == r.digest(r.canonical_csv(acquisition[0][acquisition[0].symbol == symbol]))
        assert metadata['null_row_rejection_count'] == metadata['duplicate_date_count'] == metadata['invalid_ohlc_rejection_count'] == 0
    assert manifest['ohlc_boundary_normalization']['relative_tolerance'] == 1e-12
    with pytest.raises(FileExistsError):
        r.freeze_data(*acquisition, context, tmp_path, '2026-10-07T00:00:00Z')


def test_lock_before_any_oos_price_and_no_replacement(monkeypatch, acquisition, tmp_path):
    mock_context(monkeypatch)
    monkeypatch.setattr(r.yahoo, 'acquire_data', lambda: acquisition)
    original = r.run_tournament
    observed = []
    def tournament(frame):
        maximum = max(frame.date)
        observed.append(maximum)
        if len(observed) == 1:
            assert maximum == '2019-12-31'
            assert not (tmp_path / 'trend_stage_a_selection_lock.json').exists()
            assert (tmp_path / 'trend_stage_a_data_manifest.json').exists()
        else:
            lock = json.loads((tmp_path / 'trend_stage_a_selection_lock.json').read_text())
            assert lock['protocol_id'] == r.PROTOCOL_ID
            assert lock['selection_ranking_sha256'] == r.digest((tmp_path / 'trend_stage_a_selection_ranking.csv').read_bytes())
            assert maximum == '2026-09-30'
        return original(frame)
    monkeypatch.setattr(r, 'run_tournament', tournament)
    result = r.run_research(tmp_path)
    assert observed == ['2019-12-31', '2026-09-30']
    lock = json.loads((tmp_path / 'trend_stage_a_selection_lock.json').read_text())
    report = json.loads((tmp_path / 'trend_stage_a_report.json').read_text())
    assert result.selection_winner == lock['provisional_selection_winner'] == report['selection_winner']
    assert result.oos_validation_status == 'FAIL' and result.final_winner is None
    assert report['winner_selected'] is False and report['production_trend_detector_created'] is False
    hashes = json.loads((tmp_path / 'trend_stage_a_artifact_hashes.json').read_text())
    assert all(h == r.digest((tmp_path / path).read_bytes()) for path, h in hashes.items())
    assert len(pd.read_csv(tmp_path / 'trend_stage_a_selection_ranking.csv')) == 5
    assert len(pd.read_csv(tmp_path / 'trend_stage_a_oos_ranking.csv')) == 5
    assert report['locked_candidate_primary_symbol_medians']['selection']['mfe_60_median'] is None


def test_mutated_snapshot_stops_before_oos(monkeypatch, acquisition, tmp_path):
    mock_context(monkeypatch)
    monkeypatch.setattr(r.yahoo, 'acquire_data', lambda: acquisition)
    original = r.run_tournament
    calls = []
    def tournament(frame):
        calls.append(1)
        result = original(frame)
        with (tmp_path / 'stage_a_adjusted_daily.csv').open('ab') as out:
            out.write(b'\n')
        return result
    monkeypatch.setattr(r, 'run_tournament', tournament)
    with pytest.raises(r.StageARunError, match='changed'):
        r.run_research(tmp_path)
    assert len(calls) == 1
    assert not (tmp_path / 'trend_stage_a_report.json').exists()


def test_nonempty_destination_prevents_fetch(monkeypatch, tmp_path):
    mock_context(monkeypatch)
    (tmp_path / 'previous.json').write_text('{}')
    acquisition = Mock()
    monkeypatch.setattr(r.yahoo, 'acquire_data', acquisition)
    with pytest.raises(r.StageARunError, match='empty'):
        r.run_research(tmp_path)
    acquisition.assert_not_called()


def test_dirty_source_stops_before_fetch(monkeypatch, tmp_path):
    acquisition = Mock()
    monkeypatch.setattr(r.yahoo, 'acquire_data', acquisition)
    monkeypatch.setattr(r.subprocess, 'check_output', lambda *args, **kwargs: ' M source.py\n')
    with pytest.raises(r.StageARunError, match='Clean'):
        r.run_research(tmp_path)
    acquisition.assert_not_called()


def test_failure_has_no_verdict_or_lock(monkeypatch, tmp_path):
    mock_context(monkeypatch)
    def fail():
        raise r.yahoo.StageADataError('SPY unavailable')
    monkeypatch.setattr(r.yahoo, 'acquire_data', fail)
    with pytest.raises(r.yahoo.StageADataError):
        r.run_research(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_repeatable_freeze_with_recorded_timestamp(acquisition, tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    context = dict(execution_commit='c' * 40)
    r.freeze_data(*acquisition, context, a, '2026-10-07T01:02:03Z')
    r.freeze_data(*acquisition, context, b, '2026-10-07T01:02:03Z')
    assert {p.name:p.read_bytes() for p in a.iterdir()} == {p.name:p.read_bytes() for p in b.iterdir()}
