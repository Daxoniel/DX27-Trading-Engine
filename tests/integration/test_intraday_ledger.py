from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from dx27.adapters.intraday.cli import create_demo, main, write_report
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.application.intraday_replay import IntradayLedgerReplay
from dx27.core.models.execution_costs import ExecutionCosts
from dx27.domains.intraday.replay_config import IntradayReplayConfig


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "demo.csv"
    create_demo(path)
    return load_csv(path)


def run(dataset, **changes):
    return IntradayLedgerReplay(IntradayReplayConfig(**changes)).run(dataset)


def one_symbol(dataset):
    return IntradayDataset(tuple(b for b in dataset.bars if b.symbol == "SPY"),
                           dict(dataset.provenance, symbols=["SPY"]))


def change_bar(dataset, symbol, at, **changes):
    return IntradayDataset(tuple(replace(b, **changes) if b.symbol == symbol and b.timestamp == at else b
                                 for b in dataset.bars), dataset.provenance)


def test_multisymbol_demo_reconciles_cash_and_every_component_of_pnl(dataset):
    result = run(dataset)
    assert result.summary["status"] == "COMPLETE_REPLAY"
    assert result.summary["performance_admissible"] is False  # synthetic evidence
    assert result.summary["production_enabled"] is False
    assert result.summary["trades"] == 6
    assert {t["symbol"] for t in result.trades} == {"SPY", "QQQ", "IWM"}
    assert result.summary["ending_cash"] == pytest.approx(100_000 + sum(f["cash_delta"] for f in result.fills))
    assert result.summary["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in result.trades))
    assert result.summary["net_pnl"] == pytest.approx(sum(t["gross_pnl"] for t in result.trades)
                                                   - sum(t["commission"] + t["spread_cost"] + t["slippage_cost"] for t in result.trades))
    for row in result.equity:
        assert row["equity"] == pytest.approx(row["cash"] + row["holdings_value"])
        assert row["cash"] >= 0
    for fill in result.fills:
        if fill["side"] == "buy":
            assert datetime.fromisoformat(fill["timestamp"]) > datetime.fromisoformat(fill["decision_at"])
            assert fill["quantity"] * fill["price"] <= 0.25 * 100_100
    assert all(t["planned_stop_risk"] <= 0.0025 * 100_100 for t in result.trades)


def test_gap_stop_uses_worse_open_and_records_actual_costs(dataset):
    dataset = one_symbol(dataset)
    buy = next(f for f in run(dataset).fills if f["side"] == "buy")
    at = datetime.fromisoformat(buy["timestamp"]) + timedelta(minutes=1)
    gapped = change_bar(dataset, "SPY", at, open=90, high=90.2, low=89.8, close=90.1)
    result = run(gapped)
    trade = result.trades[0]
    assert trade["exit_reason"] == "gap_stop"
    assert trade["exit_price"] < 90
    assert trade["net_pnl"] < -trade["planned_stop_risk"]
    assert result.daily[0]["daily_loss_halted"]


def test_intraminute_stop_target_ambiguity_and_known_opening_target_are_distinct(dataset):
    dataset = one_symbol(dataset)
    result = run(dataset)
    buy = next(f for f in result.fills if f["side"] == "buy")
    decision = next(d for d in result.decisions if d["action"] == "QUEUE_LONG")
    atr = decision["atr"]
    at = datetime.fromisoformat(buy["timestamp"]) + timedelta(minutes=1)
    reference = buy["price"]
    ambiguous = change_bar(dataset, "SPY", at, open=reference, close=reference,
                           low=reference - 2*atr, high=reference + 3*atr)
    report = run(ambiguous)
    assert report.trades[0]["exit_reason"] == "stop_loss"
    assert any(q["code"] == "AMBIGUOUS_STOP_FIRST" for q in report.quality)
    exit_fill = report.fills[1]
    assert exit_fill["time_precision"] == "BAR_INTERVAL"
    target_gap = change_bar(ambiguous, "SPY", at, open=reference + 2.5*atr)
    assert run(target_gap).trades[0]["exit_reason"] == "gap_target"


def test_missing_opening_minute_prevents_trading_and_missing_held_minute_invalidates_results(dataset):
    dataset = one_symbol(dataset)
    first = dataset.bars[0]
    missing_open = IntradayDataset(tuple(b for b in dataset.bars if b != first), dataset.provenance)
    report = run(missing_open)
    assert not any(t["entry_time"].startswith("2025-11-26") for t in report.trades)
    buy = next(f for f in run(dataset).fills if f["side"] == "buy")
    at = datetime.fromisoformat(buy["timestamp"]) + timedelta(minutes=1)
    missing_held = IntradayDataset(tuple(b for b in dataset.bars if b.timestamp != at), dataset.provenance)
    report = run(missing_held)
    assert report.summary["net_pnl"] is None
    assert report.summary["performance_admissible"] is False
    assert report.trades[0]["exit_reason"] == "data_gap_recovery"
    assert report.trades[0]["path_complete"] is False
    assert any(q["code"] == "MISSING_HELD_BAR" for q in report.quality)


def test_future_gap_and_future_extremes_do_not_change_earlier_fills_or_decisions(dataset):
    dataset = one_symbol(dataset)
    original = run(dataset)
    late = next(b for b in dataset.bars if b.timestamp.isoformat().startswith("2025-11-26T20:30"))
    changed = change_bar(dataset, "SPY", late.timestamp, open=300, high=1000, low=1, close=500, volume=9_999_999)
    deleted = IntradayDataset(tuple(b for b in dataset.bars if b != late), dataset.provenance)
    for variant in (changed, deleted):
        report = run(variant)
        assert [f for f in report.fills if f["timestamp"] < late.timestamp.isoformat()] == [
            f for f in original.fills if f["timestamp"] < late.timestamp.isoformat()]
        assert [d for d in report.decisions if d["decision_at"] < late.timestamp.isoformat()] == [
            d for d in original.decisions if d["decision_at"] < late.timestamp.isoformat()]


def test_entry_size_does_not_use_future_fill_bar_volume(dataset):
    dataset = one_symbol(dataset)
    original = run(dataset)
    buy = next(f for f in original.fills if f["side"] == "buy")
    changed = change_bar(dataset, "SPY", datetime.fromisoformat(buy["timestamp"]), volume=1)
    assert next(f for f in run(changed).fills if f["side"] == "buy") == buy


def test_early_close_flattens_at_calendar_time_and_input_order_cannot_change_allocations(dataset):
    cfg = dict(target_atr=1_000_000)
    original = run(dataset, **cfg)
    reverse = IntradayDataset(tuple(reversed(dataset.bars)), dataset.provenance)
    assert run(reverse, **cfg).fills == original.fills
    exits = [f for f in original.fills if f["reason"] == "scheduled_flatten"]
    assert len(exits) == 6
    assert {f["timestamp"] for f in exits if f["timestamp"].startswith("2025-11-28")} == {"2025-11-28T17:55:00+00:00"}
    assert len(original.daily) == 2  # Thanksgiving is closed, not a missing trading day.
    assert original.summary["open_positions"] == 0


def test_missing_flatten_and_remaining_bars_preserves_unresolved_position(dataset):
    dataset = one_symbol(dataset)
    partial = IntradayDataset(tuple(b for b in dataset.bars if b.timestamp.isoformat() < "2025-11-26T20:55"), dataset.provenance)
    report = run(partial, target_atr=1_000_000)
    assert report.summary["open_positions"] == 1
    assert report.summary["net_pnl"] is None
    assert not any(f["reason"] == "scheduled_flatten" for f in report.fills)
    assert any(q["code"] == "UNRESOLVED_AT_CLOSE" for q in report.quality)


def test_warmup_period_never_trades_and_position_limit_is_account_wide(dataset):
    report = run(dataset, decision_start=date(2025, 11, 28), max_positions=1)
    assert len(report.trades) == 1
    assert report.trades[0]["entry_time"].startswith("2025-11-28")
    assert any(d["reason"] == "maximum_positions" for d in report.decisions)
    assert not report.daily[0]["decision_period"]


def test_zero_volume_does_not_become_verified_execution_evidence(dataset):
    first = dataset.bars[0]
    changed = change_bar(dataset, first.symbol, first.timestamp, volume=0)
    report = run(changed)
    assert report.summary["net_pnl"] is None
    assert any(q["code"] == "ZERO_VOLUME_MINUTE" for q in report.quality)


def test_declared_request_period_keeps_a_whole_missing_session_in_the_denominator(dataset):
    only_last = IntradayDataset(tuple(b for b in dataset.bars if b.timestamp.date() == date(2025, 11, 28)),
                               dict(dataset.provenance, start="2025-11-26T00:00:00Z",
                                    end_exclusive="2025-11-29T00:00:00Z"))
    report = run(only_last)
    assert [d["session"] for d in report.daily] == ["2025-11-26", "2025-11-28"]
    assert report.daily[0]["data_complete"] is False
    assert report.summary["net_pnl"] is None


def test_costs_trigger_account_halt_before_later_simultaneous_entries(dataset):
    report = run(dataset, daily_loss_limit=0.000001)
    first_day_buys = [f for f in report.fills if f["side"] == "buy" and f["timestamp"].startswith("2025-11-26")]
    assert len(first_day_buys) == 1
    assert report.daily[0]["daily_loss_halted"]
    assert any(d["reason"] == "account_halted" for d in report.decisions)


def test_report_and_cli_make_incomplete_data_an_explicit_nonzero_exit(dataset, tmp_path):
    report = run(dataset)
    target = tmp_path / "report"
    write_report(report, target)
    assert {p.name for p in target.iterdir()} == {"summary.json", "report.md", "fills.csv", "trades.csv",
                                                "daily.csv", "equity.csv", "decisions.csv", "data-quality.csv"}
    assert "合成演示" in (target / "report.md").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_report(report, target)
    partial = tmp_path / "partial.csv"
    partial.write_text("symbol,timestamp,open,high,low,close,volume\nSPY,2025-11-26T14:30:00Z,100,101,99,100,500\n")
    assert main(["replay", "--input", str(partial), "--output", str(tmp_path / "partial-report")]) == 2


@pytest.mark.parametrize("values", [{"initial_cash": float("nan")}, {"execution_delay_minutes": 0},
                                    {"risk_per_trade": 0}, {"max_positions": 1.5}, {"stop_atr": float("inf")}])
def test_invalid_engineering_limits_fail_before_replay(values):
    with pytest.raises(ValueError):
        IntradayReplayConfig(**values)
