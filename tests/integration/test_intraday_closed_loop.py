from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.closed_loop import main, run_closed_loop
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.application.intraday_closed_loop import ClosedLoopReplay
from dx27.application.intraday_replay import IntradayLedgerReplay
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "demo.csv"
    create_demo(path)
    return load_csv(path)


def run(root, dataset, profile=None, config=None, observer=None):
    config = config or IntradayReplayConfig()
    with OfflineOrderBook(root / "orders.sqlite3", "test", config.initial_cash) as book:
        with ScriptedBroker(root / "broker.sqlite3", "test", config.initial_cash) as broker:
            engine = ClosedLoopReplay(config, profile, book, broker)
            result = engine.run(dataset, observer=observer)
            return result, engine.execution_events, book.snapshot()


def changed(dataset, at, **values):
    return IntradayDataset(tuple(replace(bar, **values) if bar.timestamp == at else bar for bar in dataset.bars), dataset.provenance)


def rows(path):
    with sqlite3.connect(path) as db:
        return list(db.execute("SELECT * FROM frames ORDER BY sequence"))


@pytest.mark.parametrize("volume", [None, OpeningVolumeConfig(1, 1)])
def test_immediate_control_matches_legacy_signals_fills_and_net_cash(dataset, tmp_path, volume):
    config = IntradayReplayConfig(opening_volume=volume)
    legacy = IntradayLedgerReplay(config).run(dataset)
    result, events, state = run(tmp_path, dataset, config=config)
    assert result.decisions == legacy.decisions
    assert result.selections == legacy.selections
    for field in ("symbol", "side", "quantity", "timestamp", "reason", "decision_at"):
        assert [r[field] for r in result.fills] == [r[field] for r in legacy.fills]
    assert result.summary["ending_cash"] == pytest.approx(legacy.summary["ending_cash"], abs=1e-6)
    assert result.summary["completed_round_trips"] == legacy.summary["trades"]
    assert result.summary["status"] == "COMPLETE_REPLAY"
    assert state["positions"] == {} and state["integrity_halt"] is None
    assert all(e["orders_reconciled"] for e in result.equity)
    assert all(e["equity"] == pytest.approx(e["broker_equity"], abs=1e-6) for e in result.equity)


def test_delayed_partial_prices_and_actual_position_feedback_are_clocked(dataset, tmp_path):
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, exit_delay_minutes=1, fill_fraction=.5,
                                         entry_reservation_buffer_bps=100)
    result, events, state = run(tmp_path, dataset, profile)
    intentions = {e["client_order_id"]: e for e in events if e["kind"] == "INTENT_CREATED"}
    buys = [f for f in result.fills if f["side"] == "buy"]
    first = buys[0]
    submitted = datetime.fromisoformat(intentions[first["client_order_id"]]["received_at"])
    assert datetime.fromisoformat(first["timestamp"]) == submitted + timedelta(minutes=2)
    price = next(b.open for b in dataset.bars if b.symbol == first["symbol"] and b.timestamp == datetime.fromisoformat(first["timestamp"]))
    assert first["reference_price"] == price
    assert first["quantity"] < first["requested_quantity"]
    at = datetime.fromisoformat(first["timestamp"]) + timedelta(minutes=1)
    row = next(r for r in result.equity if datetime.fromisoformat(r["timestamp"]) == at)
    assert row["reported_positions"][first["symbol"]] == first["quantity"]
    assert row["entry_reserved_risk"] > 0 and row["reserved_cash"] > 0
    assert result.summary["open_positions"] == result.summary["active_orders"] == 0
    assert result.summary["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in result.trades), abs=1e-6)
    assert float(state["cash"]) == pytest.approx(100000 + sum(f["cash_delta"] for f in result.fills), abs=1e-6)


def test_pending_unfilled_orders_consume_position_slots_and_risk_budget(dataset, tmp_path):
    profile = HistoricalExecutionProfile(entry_delay_minutes=3, fill_fraction=.5, entry_reservation_buffer_bps=100)
    cfg = IntradayReplayConfig(max_positions=1, max_open_risk=.0001, target_atr=1e6)
    result, events, state = run(tmp_path, dataset, profile, cfg)
    submitted = [e for e in events if e["kind"] == "INTENT_CREATED" and e["side"] == "buy"]
    assert len(submitted) == 2
    assert all(e["planned_risk"] <= e["planning_equity"] * cfg.max_open_risk for e in submitted)
    assert any(r["open_positions"] == 0 and r["active_orders"] == 1 and r["entry_reserved_risk"] > 0 for r in result.equity)
    assert any(d["action"] == "REJECT_ENTRY" for d in result.decisions)
    assert max(r["open_positions"] for r in result.equity) == 1


def test_partial_entry_stop_cancels_remaining_buy_before_selling_only_filled_shares(dataset, tmp_path):
    one = IntradayDataset(tuple(b for b in dataset.bars if b.symbol == "SPY"), dict(dataset.provenance, symbols=["SPY"]))
    profile = HistoricalExecutionProfile(fill_fraction=.5, entry_reservation_buffer_bps=100, lose_cancel_replies=True)
    control, _, _ = run(tmp_path / "reference", one, profile, IntradayReplayConfig(target_atr=1e6))
    first = next(f for f in control.fills if f["side"] == "buy")
    at = datetime.fromisoformat(first["timestamp"])
    gapped = changed(one, at, low=90, high=first["reference_price"] + .1)
    result, events, state = run(tmp_path / "stop", gapped, profile, IntradayReplayConfig(target_atr=1e6))
    entry = next(f for f in result.fills if f["side"] == "buy")
    same_order = [f for f in result.fills if f["client_order_id"] == entry["client_order_id"]]
    assert len(same_order) == 1  # The remaining entry quantity was canceled.
    assert any(e["kind"] == "CANCEL_UNKNOWN" for e in events)
    assert any(d["action"] == "WAIT_EXIT" for d in result.decisions)
    exits = [f for f in result.fills if f["side"] == "sell" and f["timestamp"].startswith("2025-11-26")]
    assert sum(f["quantity"] for f in exits) == entry["quantity"]
    assert min(f["timestamp"] for f in exits) > entry["timestamp"]
    assert result.summary["status"] == "COMPLETE_REPLAY" and state["positions"] == {}


def test_daily_loss_cancels_pending_entries_and_flattens_actual_partial_inventory(dataset, tmp_path):
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, exit_delay_minutes=1, fill_fraction=.5,
                                         entry_reservation_buffer_bps=100)
    result, events, state = run(tmp_path, dataset, profile, IntradayReplayConfig(daily_loss_limit=.000001))
    assert all(row["daily_loss_halted"] for row in result.daily)
    for day in ("2025-11-26", "2025-11-28"):
        assert len({f["client_order_id"] for f in result.fills if f["side"] == "buy" and f["timestamp"].startswith(day)}) == 1
    assert all(t["exit_reason"] == "daily_loss_limit" for t in result.trades)
    assert result.summary["status"] == "COMPLETE_REPLAY" and state["positions"] == {}


def test_rejected_entries_never_create_phantom_positions_or_pnl(dataset, tmp_path):
    result, events, state = run(tmp_path, dataset, HistoricalExecutionProfile(reject_every_nth_entry=1))
    assert result.fills == result.trades == []
    assert result.summary["net_pnl"] == 0 and result.summary["ending_cash"] == 100000
    assert all(o["state"] == "REJECTED" for o in state["orders"].values())
    assert result.summary["status"] == "COMPLETE_REPLAY"


@pytest.mark.parametrize("outcome", ["accepted", "not_found"])
def test_unknown_submission_pauses_entry_until_authoritative_query_and_never_retries(dataset, tmp_path, outcome):
    profile = HistoricalExecutionProfile(uncertain_every_nth_entry=1, uncertainty_mode=outcome,
                                         fill_fraction=.5, entry_reservation_buffer_bps=100)
    result, events, state = run(tmp_path, dataset, profile)
    assert any(e["kind"] == "SUBMIT_UNKNOWN" for e in events)
    if outcome == "accepted":
        assert any(f["received_at"] > f["timestamp"] for f in result.fills)
        assert any(not r["orders_reconciled"] for r in result.equity)
        assert result.summary["simulator_submit_calls"] == result.summary["order_count"]
        assert result.summary["status"] == "COMPLETE_REPLAY" and state["positions"] == {}
    else:
        assert result.summary["simulator_submit_calls"] == 0
        assert result.summary["order_count"] == 1 and result.fills == []
        assert result.summary["status"] == "INCOMPLETE_DATA_OR_UNRESOLVED_POSITIONS"
        assert result.summary["net_pnl"] is None and result.summary["broker_maximum_drawdown"] is None


def test_early_close_delayed_exit_is_not_faked_flat_when_outside_the_clock(dataset, tmp_path):
    profile = HistoricalExecutionProfile(exit_delay_minutes=6)
    cfg = IntradayReplayConfig(target_atr=1e6)
    result, events, state = run(tmp_path, dataset, profile, cfg)
    assert result.summary["status"] == "INCOMPLETE_DATA_OR_UNRESOLVED_POSITIONS"
    assert result.summary["net_pnl"] is None and result.summary["open_positions"] > 0
    assert any(q["code"] == "UNRESOLVED_ORDER_AT_CLOSE" and q["session"] == "2025-11-28" for q in result.quality)
    assert not any(f["timestamp"] >= "2025-11-28T18:00:00+00:00" for f in result.fills)


def test_future_volume_and_prices_do_not_change_earlier_decisions_or_received_facts(dataset, tmp_path):
    cutoff = next(b.timestamp for b in dataset.bars if b.timestamp.isoformat().startswith("2025-11-26T20:30"))
    variant = IntradayDataset(tuple(replace(b, volume=1e12, open=300, high=301, low=299, close=300) if b.timestamp >= cutoff else b for b in dataset.bars), dataset.provenance)
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, fill_fraction=.5, entry_reservation_buffer_bps=100)
    seen = []
    for i, source in enumerate((dataset, variant)):
        frames = []
        run(tmp_path / str(i), source, profile, observer=lambda frame: frames.append(frame) if datetime.fromisoformat(frame["as_of"]) < cutoff else None)
        seen.append(frames)
    assert seen[0] == seen[1]


def test_warmup_and_missing_held_minutes_remain_gated(dataset, tmp_path):
    profile = HistoricalExecutionProfile(fill_fraction=.5, entry_reservation_buffer_bps=100)
    config = IntradayReplayConfig(decision_start=date(2025, 11, 28), target_atr=1e6)
    control, _, _ = run(tmp_path / "reference", dataset, profile, config)
    assert all(f["timestamp"].startswith("2025-11-28") for f in control.fills)
    first = next(f for f in control.fills if f["side"] == "buy")
    at = datetime.fromisoformat(first["timestamp"]) + timedelta(minutes=1)
    missing = IntradayDataset(tuple(b for b in dataset.bars if b.timestamp != at), dataset.provenance)
    result, events, state = run(tmp_path / "missing", missing, profile, config)
    assert result.summary["net_pnl"] is None
    assert any(q["code"] == "MISSING_HELD_BAR" for q in result.quality)
    assert any(t["exit_reason"] == "data_gap_recovery" for t in result.trades)


def test_closed_loop_journal_pause_rebuild_and_repeat_have_identical_committed_records(dataset, tmp_path):
    journal = tmp_path / "closed.sqlite3"
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, fill_fraction=.5, entry_reservation_buffer_bps=100)
    receipt, partial = run_closed_loop(dataset, journal, profile=profile, stop_after_minutes=101)
    assert receipt["status"] == "PAUSED" and partial is None
    prefix = rows(journal)
    completed, result = run_closed_loop(dataset, journal, profile=profile)
    assert completed["verified_prefix_frames"] == len(prefix)
    assert rows(journal)[:len(prefix)] == prefix
    prior = rows(journal)
    repeated, same = run_closed_loop(dataset, journal, profile=profile)
    assert repeated["appended_frames"] == 0 and rows(journal) == prior
    assert asdict(result) == asdict(same)
    assert any(json.loads(row[2]).get("orders") for row in prior)
    assert any(json.loads(row[2]).get("execution_events") for row in prior)
    with pytest.raises(ValueError, match="mismatch"):
        run_closed_loop(dataset, journal, profile=replace(profile, fill_fraction=.25))


def test_process_death_after_committed_minute_rebuilds_exactly_once(dataset, tmp_path):
    source = tmp_path / "demo.csv"
    journal = tmp_path / "crash.sqlite3"
    script = """
import os, sys
from dx27.adapters.intraday.recorded_shadow import ShadowJournal
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.closed_loop import run_closed_loop
original=ShadowJournal.append
def killed(self, frame):
    original(self, frame)
    if any(f['side']=='buy' for f in frame.get('fills', [])):
        os._exit(17)
ShadowJournal.append=killed
run_closed_loop(load_csv(sys.argv[1]),sys.argv[2])
"""
    process = subprocess.run([sys.executable, "-c", script, str(source), str(journal)], timeout=30)
    assert process.returncode == 17
    prefix = rows(journal)
    receipt, recovered = run_closed_loop(dataset, journal)
    _, uninterrupted = run_closed_loop(dataset, tmp_path / "fresh.sqlite3")
    assert asdict(recovered) == asdict(uninterrupted)
    assert receipt["verified_prefix_frames"] == len(prefix)
    assert rows(journal)[:len(prefix)] == prefix


def test_cli_keeps_rvol_selections_and_labels_framework_scope(dataset, tmp_path, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"opening_volume": {"lookback_sessions": 1, "minimum_rvol": 1}}))
    output = tmp_path / "report"
    assert main(["--input", str(tmp_path / "demo.csv"), "--journal", str(tmp_path / "cli.sqlite3"),
                 "--config", str(config), "--output", str(output)]) == 0
    assert (output / "selection.csv").exists()
    receipt = json.loads((output / "closed-loop-receipt.json").read_text(encoding="utf-8"))
    assert receipt["real_broker_orders_enabled"] is False and receipt["algorithm_optimization_performed"] is False


@pytest.mark.parametrize("values", [{"fill_fraction": 0}, {"entry_delay_minutes": -1}, {"exit_delay_minutes": True},
                                    {"entry_reservation_buffer_bps": float("nan")}, {"uncertainty_mode": "live"}])
def test_invalid_scenario_profiles_fail_before_execution(values):
    with pytest.raises(ValueError):
        HistoricalExecutionProfile(**values)


def test_current_execution_minute_volume_is_not_used_before_the_minute_finishes(dataset, tmp_path):
    profile = HistoricalExecutionProfile(entry_delay_minutes=2, fill_fraction=.5, entry_reservation_buffer_bps=100)
    control, _, _ = run(tmp_path / "control", dataset, profile)
    first = next(f for f in control.fills if f["side"] == "buy")
    source = changed(dataset, datetime.fromisoformat(first["timestamp"]), volume=0)
    result, events, _ = run(tmp_path / "zero", source, profile)
    same = next(f for f in result.fills if f["side"] == "buy")
    assert same["timestamp"] == first["timestamp"] and same["quantity"] == first["quantity"]
    assert any(q["code"] == "ZERO_VOLUME_MINUTE" for q in result.quality)
    assert result.summary["net_pnl"] is None


def test_closed_loop_refuses_foreign_order_database_without_schema_mutation(dataset, tmp_path):
    path = tmp_path / "orders.sqlite3"
    with OfflineOrderBook(path, "foreign", 100000):
        pass
    original = path.read_bytes()
    with pytest.raises(ValueError, match="mismatch"):
        run_closed_loop(dataset, path)
    assert path.read_bytes() == original
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='frames'").fetchone() is None
