from dataclasses import asdict, replace
from datetime import date, datetime
import json
import sqlite3
import subprocess
import sys

import pytest

from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.adapters.intraday.recorded_shadow import ShadowJournal, main, manifest_for, run_recorded_shadow
from dx27.application.intraday_replay import IntradayLedgerReplay
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "demo.csv"
    create_demo(path)
    return path, load_csv(path)


def frames(path):
    with sqlite3.connect(path) as db:
        return list(db.execute("SELECT sequence, frame_key, payload, chain FROM frames ORDER BY sequence"))


@pytest.mark.parametrize("rvol", [None, OpeningVolumeConfig(1, 1)])
def test_minute_batches_match_shared_replay_and_resume_has_no_duplicate_orders(source, tmp_path, rvol):
    _, dataset = source
    cfg = IntradayReplayConfig(opening_volume=rvol, target_atr=1_000_000)
    baseline = IntradayLedgerReplay(cfg).run(dataset)
    journal = tmp_path / "shadow.sqlite3"
    paused, result = run_recorded_shadow(dataset, journal, cfg, stop_after_minutes=101)
    assert result is None and paused["status"] == "PAUSED"
    prefix = frames(journal)
    completed, result = run_recorded_shadow(dataset, journal, cfg)
    assert asdict(result) == asdict(baseline)
    assert completed["verified_prefix_frames"] == len(prefix)
    assert frames(journal)[:len(prefix)] == prefix
    rows = [json.loads(row[2]) for row in frames(journal)]
    for table in ("fills", "trades", "decisions", "equity", "daily", "selections"):
        assert [record for row in rows for record in row.get(table, [])] == getattr(baseline, table)
    assert len(rows) == 390 + 210 + 2 + 1
    assert sum(row["kind"] == "SESSION_COMPLETED" for row in rows) == 2
    assert rows[-2]["as_of"] == "2025-11-28T18:00:00+00:00"
    for row in rows[:-1]:
        assert row["hypothetical"]
        assert all(datetime.fromisoformat(d["decision_at"]) <= datetime.fromisoformat(row["as_of"])
                   for d in row["decisions"])
    assert not completed["broker_orders_enabled"] and not completed["realtime_data_verified"]
    previous = frames(journal)
    again, same_result = run_recorded_shadow(dataset, journal, cfg)
    assert again["appended_frames"] == 0
    assert again["verified_prefix_frames"] == len(previous)
    assert frames(journal) == previous and asdict(same_result) == asdict(baseline)


def test_abrupt_process_exit_with_open_hypothetical_position_recovers_identically(source, tmp_path):
    path, dataset = source
    journal = tmp_path / "crash.sqlite3"
    script = """
import os, sys
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.recorded_shadow import ShadowJournal, run_recorded_shadow
from dx27.domains.intraday.replay_config import IntradayReplayConfig
original = ShadowJournal.append
def crash_after_commit(self, frame):
    original(self, frame)
    if any(f['side'] == 'buy' for f in frame.get('fills', [])):
        os._exit(17)
ShadowJournal.append = crash_after_commit
run_recorded_shadow(load_csv(sys.argv[1]), sys.argv[2], IntradayReplayConfig(target_atr=1000000))
"""
    child = subprocess.run([sys.executable, "-c", script, str(path), str(journal)], timeout=30)
    assert child.returncode == 17
    prefix = frames(journal)
    assert any(f["side"] == "buy" for f in json.loads(prefix[-1][2])["fills"])
    cfg = IntradayReplayConfig(target_atr=1_000_000)
    receipt, recovered = run_recorded_shadow(dataset, journal, cfg)
    assert receipt["verified_prefix_frames"] == len(prefix)
    assert recovered.summary["open_positions"] == 0
    assert asdict(recovered) == asdict(IntradayLedgerReplay(cfg).run(dataset))


def test_input_config_and_source_revision_cannot_rewrite_a_committed_prefix(source, tmp_path):
    _, dataset = source
    path = tmp_path / "journal.sqlite3"
    run_recorded_shadow(dataset, path, stop_after_minutes=2)
    previous = frames(path)
    changed_bar = replace(dataset.bars[-1], volume=dataset.bars[-1].volume + 1)
    revisions = [IntradayDataset(dataset.bars[:-1] + (changed_bar,), dataset.provenance),
                 IntradayDataset(dataset.bars, dict(dataset.provenance, feed="iex"))]
    for variant in revisions:
        with pytest.raises(ValueError, match="mismatch"):
            run_recorded_shadow(variant, path)
    with pytest.raises(ValueError, match="mismatch"):
        run_recorded_shadow(dataset, path, IntradayReplayConfig(decision_start=date(2025, 11, 28)))
    assert frames(path) == previous


def test_journal_corruption_and_second_writer_fail_closed(source, tmp_path):
    _, dataset = source
    path = tmp_path / "journal.sqlite3"
    run_recorded_shadow(dataset, path, stop_after_minutes=2)
    with ShadowJournal(path, manifest_for(dataset, IntradayReplayConfig())):
        with pytest.raises(sqlite3.OperationalError):
            run_recorded_shadow(dataset, path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE frames SET payload='{}' WHERE sequence=1")
    with pytest.raises(ValueError, match="integrity"):
        run_recorded_shadow(dataset, path)


def test_changed_engine_outputs_fail_prefix_verification_before_new_writes(source, tmp_path, monkeypatch):
    _, dataset = source
    path = tmp_path / "journal.sqlite3"
    run_recorded_shadow(dataset, path, stop_after_minutes=2)
    previous = frames(path)
    original = IntradayLedgerReplay.run

    def different(self, dataset, *, observer=None):
        def mutated(frame):
            frame["hypothetical"] = False
            observer(frame)
        return original(self, dataset, observer=mutated)

    monkeypatch.setattr(IntradayLedgerReplay, "run", different)
    with pytest.raises(ValueError, match="prefix differs"):
        run_recorded_shadow(dataset, path)
    assert frames(path) == previous


def test_missing_minutes_warmup_and_quality_updates_remain_explicit(source, tmp_path):
    _, dataset = source
    missing = IntradayDataset(dataset.bars[1:], dataset.provenance)
    cfg = IntradayReplayConfig(decision_start=date(2025, 11, 28))
    receipt, result = run_recorded_shadow(missing, tmp_path / "gap.sqlite3", cfg)
    assert receipt["status"] == "INCOMPLETE_RECORDED_SHADOW"
    assert result.summary["net_pnl"] is None
    assert all(f["timestamp"].startswith("2025-11-28") for f in result.fills)
    assert any(q["code"] == "MISSING_MINUTE" for q in result.quality)
    with pytest.raises(ValueError, match="duplicate"):
        run_recorded_shadow(IntradayDataset(dataset.bars + (dataset.bars[0],), dataset.provenance), tmp_path / "duplicate.sqlite3")


def test_future_bars_and_observer_mutation_do_not_change_past_engine_state(source):
    _, dataset = source
    cutoff = dataset.bars[-3].timestamp
    changed = IntradayDataset(tuple(replace(b, volume=1e10) if b.timestamp >= cutoff else b for b in dataset.bars), dataset.provenance)
    prefixes = []
    for variant in (dataset, changed):
        seen = []
        baseline = IntradayLedgerReplay().run(variant)

        def observe(frame):
            if datetime.fromisoformat(frame["as_of"]) < cutoff:
                seen.append(json.dumps(frame, sort_keys=True))
            # The observation is detached from the engine's mutable rows.
            for row in frame["equity"]:
                row["cash"] = -1

        result = IntradayLedgerReplay().run(variant, observer=observe)
        assert asdict(result) == asdict(baseline)
        prefixes.append(seen)
    assert prefixes[0] == prefixes[1]


def test_cli_runs_without_credentials_and_exports_clearly_historical_receipt(source, tmp_path, monkeypatch):
    path, _ = source
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    journal, output = tmp_path / "state.sqlite3", tmp_path / "report"
    arguments = ["--input", str(path), "--journal", str(journal)]
    assert main(arguments + ["--stop-after-minutes", "5"]) == 3
    assert main(arguments + ["--output", str(output)]) == 0
    receipt = json.loads((output / "shadow-receipt.json").read_text(encoding="utf-8"))
    assert receipt["mode"] == "RECORDED_HISTORICAL_SHADOW"
    assert receipt["verified_prefix_frames"] == 5
    with pytest.raises(SystemExit) as error:
        main(arguments + ["--output", str(output)])
    assert error.value.code == 1
