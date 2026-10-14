import json
import sqlite3

import pytest

from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.data import load_csv
from dx27.adapters.intraday.execution_conformance import main, read_shadow_trace, run_historical_trace
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.recorded_shadow import run_recorded_shadow


@pytest.fixture
def source(tmp_path):
    csv = tmp_path / "demo.csv"
    create_demo(csv)
    path = tmp_path / "shadow.sqlite3"
    run_recorded_shadow(load_csv(csv), path)
    return path


def test_offline_cli_fault_cases_and_split_historical_orders_require_no_credentials(source, tmp_path, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    output = tmp_path / "report"
    before = source.read_bytes()
    assert main(["--source-journal", str(source), "--output", str(output)]) == 0
    result = json.loads((output / "acceptance.json").read_text(encoding="utf-8"))
    assert result["scripted_fault_cases"] == 9
    assert all(case["passed"] for case in result["cases"].values())
    assert result["cases"]["submit_not_found"]["ready"] is False
    assert result["cases"]["budget_breach"]["ready"] is False
    assert result["real_broker_orders_enabled"] is False
    trace = result["historical_trace"]
    assert trace["source_fills"] == trace["orders"] == trace["submit_calls"] == 12
    assert trace["partial_reports_in_this_run"] == 12
    assert trace["positions"] == {} and trace["same_final_modeled_account"]
    assert abs(float(trace["modeled_cash_residual"])) < 1e-6
    again = run_historical_trace(source, output / "trace-state")
    assert again["new_submit_calls"] == again["partial_reports_in_this_run"] == 0
    assert again["orders"] == 12 and again["cash"] == trace["cash"]
    assert source.read_bytes() == before  # Source is read-only throughout.
    with pytest.raises(SystemExit) as error:
        main(["--source-journal", str(source), "--output", str(output)])
    assert error.value.code == 1


def test_paused_and_corrupted_shadow_sources_are_not_admitted(source, tmp_path):
    csv = tmp_path / "demo.csv"
    paused = tmp_path / "paused.sqlite3"
    run_recorded_shadow(load_csv(csv), paused, stop_after_minutes=2)
    with pytest.raises(ValueError, match="complete flat"):
        read_shadow_trace(paused)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE frames SET payload='{}' WHERE sequence=1")
    with pytest.raises(ValueError, match="integrity"):
        read_shadow_trace(source)


def test_wrong_database_contract_does_not_modify_source_schema_or_contents(source):
    before = source.read_bytes()
    with pytest.raises(ValueError, match="mismatch"):
        OfflineOrderBook(source, "wrong", 100_000)
    assert source.read_bytes() == before
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='audit'").fetchone() is None
