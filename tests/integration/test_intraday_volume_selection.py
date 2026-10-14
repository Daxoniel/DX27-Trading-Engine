from dataclasses import replace
from datetime import datetime, timedelta
import json

import pytest

from dx27.adapters.intraday.cli import create_demo, main, read_config, write_report
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.application.intraday_replay import IntradayLedgerReplay
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "demo.csv"
    create_demo(path)
    return load_csv(path)


def run(dataset, threshold=1):
    return IntradayLedgerReplay(IntradayReplayConfig(opening_volume=OpeningVolumeConfig(1, threshold))).run(dataset)


def test_opt_in_selection_gates_only_entries_and_preserves_cost_accounting(dataset, tmp_path):
    baseline = IntradayLedgerReplay().run(dataset)
    selected = run(dataset)
    assert baseline.summary["trades"] == 6
    assert selected.summary["trades"] == 3
    assert selected.summary["task"] == "INTRA-1B"
    assert all(t["entry_time"].startswith("2025-11-28") for t in selected.trades)
    assert all(datetime.fromisoformat(f["timestamp"]) > datetime.fromisoformat(f["decision_at"])
               for f in selected.fills if f["side"] == "buy")
    assert selected.summary["accounting_reconciled"]
    assert selected.summary["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in selected.trades))
    assert selected.summary["performance_admissible"] is False
    assert run(dataset, threshold=2).summary["trades"] == 0
    target = tmp_path / "report"
    write_report(selected, target)
    assert (target / "selection.csv").exists()
    assert "INTRA-1B" in (target / "report.md").read_text()


def test_future_gap_or_extreme_volume_cannot_change_frozen_selection(dataset):
    original = run(dataset)
    late = next(b for b in dataset.bars if b.timestamp.isoformat().startswith("2025-11-26T20:30"))
    changed = IntradayDataset(tuple(replace(b, volume=1e12) if b == late else b for b in dataset.bars), dataset.provenance)
    missing = IntradayDataset(tuple(b for b in dataset.bars if b != late), dataset.provenance)
    assert run(changed).selections == original.selections
    assert run(missing).selections == original.selections


def test_whole_missing_opening_symbol_does_not_disappear_from_denominator(dataset):
    bars = tuple(b for b in dataset.bars if not (b.symbol == "SPY" and b.timestamp.isoformat().startswith("2025-11-26")))
    result = run(IntradayDataset(bars, dataset.provenance))
    spy = [r for r in result.selections if r["symbol"] == "SPY"]
    assert [r["reason"] for r in spy] == ["OPENING_INCOMPLETE", "HISTORY_INCOMPLETE"]
    assert not any(t["symbol"] == "SPY" for t in result.trades)
    assert result.summary["net_pnl"] is None


def test_volume_selection_does_not_accept_iex_or_unknown_feed(dataset):
    for metadata in ({"feed": "iex"}, {}):
        with pytest.raises(ValueError, match="SIP"):
            run(IntradayDataset(dataset.bars, metadata))


def test_csv_config_roundtrip_cli_and_input_order_invariance(dataset, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"opening_volume": {"lookback_sessions": 1, "minimum_rvol": 1}}))
    assert read_config(config_path).opening_volume == OpeningVolumeConfig(1, 1)
    assert main(["replay", "--input", str(tmp_path / "demo.csv"), "--config", str(config_path),
                 "--output", str(tmp_path / "cli-report")]) == 0
    reverse = run(IntradayDataset(tuple(reversed(dataset.bars)), dataset.provenance))
    original = run(dataset)
    assert reverse.selections == original.selections
    assert reverse.fills == original.fills
