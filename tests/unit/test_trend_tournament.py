import ast
import csv
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from dx27.intelligence.sentinel.research import trend_models
from dx27.intelligence.sentinel.research.trend_models import CANDIDATES, TrendState, lean_ema
from dx27.intelligence.sentinel.research.trend_tournament import (
    OUTPUT_FILENAMES, STAGE_A_SYMBOLS, read_csv, run_tournament, summary,
    validate_dataframe, write_outputs,
)


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "src/dx27/intelligence/sentinel/research"
RUNNER = ROOT / "runners/standalone/trend_detector_tournament.py"
IDS = {"ewmac_8_32", "ewmac_16_64", "ewmac_32_128", "ewmac_64_256", "tsmom_21", "tsmom_63",
       "tsmom_126", "tsmom_252", "lean_ema_cross_12_26"}


def frame(count=400, symbols=("SPY",), start=date(2019, 1, 1)):
    rows = []
    for j, symbol in enumerate(symbols):
        for i in range(count):
            close = 100 + j * 10 + i * 0.02 + i % 5
            rows.append(dict(symbol=symbol, date=(start + timedelta(days=i)).isoformat(),
                             open=close, high=close + 1, low=close - 1, close=close, volume=100 + i))
    return pd.DataFrame(rows)


def test_validation_sorts_without_filling_missing_days_or_adjusting_prices():
    source = frame(4, ("QQQ", "SPY"))
    source = source.drop(index=[1, 5]).iloc[::-1]
    bars = validate_dataframe(source)
    assert [(b.symbol, b.date) for b in bars] == sorted((b.symbol, b.date) for b in bars)
    assert len(bars) == 6
    assert [b.date for b in bars if b.symbol == "SPY"] == [date(2019, 1, 1), date(2019, 1, 3), date(2019, 1, 4)]
    assert {b.close for b in bars} == set(source.close)
    with pytest.raises(FrozenInstanceError):
        bars[0].close = 1


def test_duplicate_symbol_date_rejected_but_cross_symbol_date_allowed():
    source = frame(2, ("SPY", "QQQ"))
    assert len(validate_dataframe(source)) == 4
    with pytest.raises(ValueError, match="Duplicate"):
        validate_dataframe(pd.concat([source, source.iloc[[0]]], ignore_index=True))


@pytest.mark.parametrize("column", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), -1])
def test_nonfinite_or_negative_input_rejected(column, bad):
    source = frame(2).astype({column: float})
    source.loc[0, column] = bad
    with pytest.raises(ValueError):
        validate_dataframe(source)


@pytest.mark.parametrize("column", ["open", "high", "low", "close"])
def test_zero_price_rejected(column):
    source = frame(2)
    source.loc[0, column] = 0
    with pytest.raises(ValueError):
        validate_dataframe(source)


def test_zero_volume_allowed():
    source = frame(2)
    source.loc[0, "volume"] = 0
    assert validate_dataframe(source)[0].volume == 0


@pytest.mark.parametrize("column,value", [("high", 99), ("low", 101), ("open", 102), ("close", 98)])
def test_invalid_ohlc_ordering_rejected(column, value):
    source = frame(2)
    source.loc[0, column] = value
    with pytest.raises(ValueError, match="OHLC"):
        validate_dataframe(source)


@pytest.mark.parametrize("bad", ["", " SPY", "SPY ", "SP Y", None, 123])
def test_invalid_symbol_never_silently_discarded(bad):
    source = frame(2).astype({"symbol": object})
    source.loc[0, "symbol"] = bad
    with pytest.raises(ValueError, match="Symbol"):
        validate_dataframe(source)


@pytest.mark.parametrize("bad", ["01/02/2019", "2019-02-30", "2019-1-1", "2019-01-01T12:00:00Z", "", None])
def test_invalid_date_rejected_deterministically(bad):
    source = frame(2)
    source.loc[0, "date"] = bad
    with pytest.raises(ValueError):
        validate_dataframe(source)


def test_iso_dates_and_midnight_dataframe_timestamps_are_supported():
    source = frame(2)
    iso = validate_dataframe(source)
    source["date"] = pd.to_datetime(source["date"], format="%Y-%m-%d")
    assert validate_dataframe(source) == iso


def test_schema_missing_duplicate_columns_empty_and_nonnumeric_rejected():
    with pytest.raises(ValueError):
        validate_dataframe(frame(2).drop(columns="volume"))
    with pytest.raises(ValueError):
        validate_dataframe(frame(2).iloc[:0])
    with pytest.raises(ValueError):
        validate_dataframe(pd.concat([frame(2), frame(2)[["close"]]], axis=1))
    source = frame(2).astype({"close": object})
    source.loc[0, "close"] = "bad"
    with pytest.raises(ValueError):
        validate_dataframe(source)


def test_csv_preserves_symbols_and_rejects_duplicate_header(tmp_path):
    path = tmp_path / "input.csv"
    frame(2, ("NA",)).to_csv(path, index=False)
    assert validate_dataframe(read_csv(path))[0].symbol == "NA"
    path.write_text("symbol,date,open,high,low,close,volume,close\nSPY,2019-01-01,1,2,1,1,0,1\n")
    with pytest.raises(ValueError, match="headers"):
        read_csv(path)


def test_default_requires_all_stage_a_symbols_and_explicit_subset_works():
    with pytest.raises(ValueError, match="Missing requested symbols"):
        run_tournament(frame(2))
    result = run_tournament(frame(2, STAGE_A_SYMBOLS))
    assert result.input_symbols == tuple(sorted(STAGE_A_SYMBOLS))
    assert len(result.observations) == 13 * 2 * 9
    result = run_tournament(frame(2, ("SPY", "QQQ")), ["SPY"])
    assert {o.symbol for o in result.observations} == {"SPY"}
    assert result.input_symbols == ("QQQ", "SPY")
    assert result.input_rows == 4 and result.evaluated_input_rows == 2
    with pytest.raises(ValueError, match="Missing"):
        run_tournament(frame(2), ["QQQ"])
    for symbols in ([], ["SPY", "SPY"], ["SPY", ""], [" SPY"]):
        with pytest.raises(ValueError):
            run_tournament(frame(2), symbols)


def test_invalid_unselected_symbol_rows_are_still_rejected():
    source = frame(2, ("SPY", "QQQ"))
    source.loc[source.symbol == "QQQ", "volume"] = -1
    with pytest.raises(ValueError):
        run_tournament(source, ["SPY"])


def test_all_nine_candidates_ordering_and_cross_symbol_independence():
    source = frame(50, ("QQQ", "SPY"))
    result = run_tournament(source, ["SPY", "QQQ"])
    shuffled = run_tournament(source.sample(frac=1, random_state=7), ["QQQ", "SPY"])
    assert result.observations == shuffled.observations
    assert result.metrics == shuffled.metrics
    assert result.sensitivity == shuffled.sensitivity
    assert {o.candidate_id for o in result.observations} == IDS
    assert [(o.symbol, o.candidate_id, o.date) for o in result.observations] == sorted(
        (o.symbol, o.candidate_id, o.date) for o in result.observations)
    assert [(r.split, r.symbol, r.candidate_id) for r in result.metrics] == sorted(
        (r.split, r.symbol, r.candidate_id) for r in result.metrics)
    assert [(r.split, r.symbol, r.family, r.candidate_a, r.candidate_b) for r in result.sensitivity] == sorted(
        (r.split, r.symbol, r.family, r.candidate_a, r.candidate_b) for r in result.sensitivity)
    single = run_tournament(source[source.symbol == "SPY"], ["SPY"])
    assert single.observations == tuple(o for o in result.observations if o.symbol == "SPY")


def test_selection_and_oos_separated_with_full_history_warmup():
    result = run_tournament(frame(), ["SPY"])
    first_oos = [o for o in result.observations if o.date == date(2020, 1, 1)]
    assert len(first_oos) == 9
    assert all(o.is_ready for o in first_oos)
    assert {r.split for r in result.metrics} == {"selection", "out_of_sample"}
    assert len(result.metrics) == 18 and len(result.sensitivity) == 24
    for row in result.metrics:
        selected = [o for o in result.observations if o.candidate_id == row.candidate_id
                    and (o.date < date(2020, 1, 1) if row.split == "selection" else o.date >= date(2020, 1, 1))]
        assert row.values["evaluated_days"] == sum(o.is_ready for o in selected)
    long_span = next(o for o in first_oos if o.candidate_id == "ewmac_64_256")
    closes = frame().close.tolist()[:366]
    assert long_span.primary_value == lean_ema(closes, 64)[-1] - lean_ema(closes, 256)[-1]


def test_future_mutation_and_truncation_cannot_change_any_earlier_value():
    source = frame()
    cutoff = date(2019, 11, 1)
    baseline = run_tournament(source, ["SPY"])
    changed = source.copy()
    future = changed.date > cutoff.isoformat()
    for column in ("open", "high", "low", "close"):
        changed.loc[future, column] = changed.loc[future, column] * 7
    mutated = run_tournament(changed, ["SPY"])
    truncated = run_tournament(source[source.date <= cutoff.isoformat()], ["SPY"])
    prefix = tuple(o for o in baseline.observations if o.date <= cutoff)
    assert tuple(o for o in mutated.observations if o.date <= cutoff) == prefix
    assert truncated.observations == prefix
    assert any(a.primary_value != b.primary_value for a, b in zip(baseline.observations, mutated.observations))


def test_ohlcv_and_rsi_are_passive_diagnostics(monkeypatch):
    source = frame(70)
    baseline = run_tournament(source, ["SPY"])
    source["volume"] *= 500
    source["high"] *= 10
    source["low"] /= 10
    monkeypatch.setattr(trend_models, "lean_rsi_14", lambda closes: (100.0,) * len(closes))
    changed = run_tournament(source, ["SPY"])
    assert [(o.state, o.primary_value, o.normalized_score) for o in baseline.observations] == [
        (o.state, o.primary_value, o.normalized_score) for o in changed.observations]
    assert baseline.metrics == changed.metrics
    assert baseline.sensitivity == changed.sensitivity


def test_output_bytes_schema_flags_and_empty_vs_neutral(tmp_path):
    source = frame(35)
    source[["open", "close"]] = 100.0
    source["high"], source["low"] = 101.0, 99.0
    first = run_tournament(source, ["SPY"], input_metadata={"provider": "synthetic", "adjustment": "none"})
    second = run_tournament(source.iloc[::-1], ["SPY"], input_metadata={"adjustment": "none", "provider": "synthetic"})
    a, b = tmp_path / "a", tmp_path / "b"
    write_outputs(first, a)
    write_outputs(second, b)
    assert {p.name for p in a.iterdir()} == set(OUTPUT_FILENAMES)
    assert all((a / name).read_bytes() == (b / name).read_bytes() for name in OUTPUT_FILENAMES)
    with (a / "trend_states.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    unready = next(r for r in rows if r["candidate_id"] == "ewmac_8_32" and r["date"] == "2019-02-04")
    neutral = next(r for r in rows if r["candidate_id"] == "lean_ema_cross_12_26" and r["date"] == "2019-02-04")
    assert unready["state"] == "" and unready["is_ready"] == "false"
    assert neutral["state"] == "NEUTRAL" and neutral["is_ready"] == "true"
    data = json.loads((a / OUTPUT_FILENAMES[-1]).read_text())
    assert data["research_id"] == "dx27.trend_tournament.v0.1" and data["schema_version"] == 1
    assert data["winner_selected"] is False and data["production_trend_detector_created"] is False
    assert data["row_counts"] == {"input": 35, "evaluated_input": 35, "trend_states": 315, "trend_metrics": 18, "trend_sensitivity": 24}
    assert data["input_min_date"] == "2019-01-01" and data["input_max_date"] == "2019-02-04"
    assert data["input_metadata"] == {"provider": "synthetic", "adjustment": "none"}
    assert data["sigma_definition"]["adjust"] is True and data["sigma_definition"]["bias"] is False
    forbidden = {"winner", "best_model", "recommended_model", "optimal_parameter", "ranking_score", "sharpe", "sortino"}
    def keys(obj):
        if isinstance(obj, dict):
            return set(obj) | set().union(*(keys(v) for v in obj.values()))
        if isinstance(obj, list):
            return set().union(*(keys(v) for v in obj))
        return set()
    assert not (keys(data) & forbidden)
    assert not (set(first.metrics[0].values) & forbidden)


def test_state_names_bullish_bearish_serialization(tmp_path):
    source = frame(300)
    source["close"] = [100 + (i if i < 150 else 300 - i) for i in range(300)]
    source["open"] = source.close
    source["high"] = source.close + 1
    source["low"] = source.close - 1
    result = run_tournament(source, ["SPY"])
    write_outputs(result, tmp_path)
    with (tmp_path / "trend_states.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    names = {r["state"] for r in rows}
    assert "BULLISH" in names and "BEARISH" in names
    assert names <= {"", "BULLISH", "BEARISH", "NEUTRAL"}


def test_library_imports_are_isolated_and_observations_are_not_events():
    banned = {"execution", "trade", "broker", "yahoo", "yfinance", "lean", "events", "detection", "detectors", "requests", "urllib", "socket"}
    for path in [*RESEARCH.glob("*.py"), RUNNER]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [alias.name for alias in node.names]
            else:
                continue
            assert not any(set(name.split(".")) & banned for name in names), path
    from dx27.intelligence.sentinel.events import DetectedEvent
    result = run_tournament(frame(40), ["SPY"])
    assert not any(isinstance(o, DetectedEvent) for o in result.observations)
    production_init = (RESEARCH.parent / "__init__.py").read_text()
    assert "research" not in production_init and "TrendChangeDetector" not in production_init
    assert not hasattr(result.observations[0], "forward_return")


def test_diagnostic_mapping_defensively_copied():
    observation = run_tournament(frame(2), ["SPY"]).observations[0]
    diagnostics = {"future_diagnostic": 1.0}
    copied = replace(observation, diagnostics=diagnostics)
    diagnostics["future_diagnostic"] = 2
    assert copied.diagnostics["future_diagnostic"] == 1
    assert copied.state == observation.state


def test_cli_smoke_and_repeatability_offline(tmp_path):
    path, destination = tmp_path / "input.csv", tmp_path / "outputs"
    frame().to_csv(path, index=False)
    command = [sys.executable, str(RUNNER), "--input-csv", str(path), "--output-dir", str(destination), "--symbols", "SPY"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "3600 research states, 18 metric rows, 24 sensitivity rows" in completed.stdout
    previous = {name: (destination / name).read_bytes() for name in OUTPUT_FILENAMES}
    repeated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert repeated.returncode == 0, repeated.stderr
    assert previous == {name: (destination / name).read_bytes() for name in OUTPUT_FILENAMES}
    metadata = json.loads((destination / OUTPUT_FILENAMES[-1]).read_text())["input_metadata"]
    assert len(metadata["sha256"]) == 64 and "timestamp" not in metadata


def test_cli_missing_default_universe_fails_without_outputs(tmp_path):
    path, destination = tmp_path / "input.csv", tmp_path / "outputs"
    frame(2).to_csv(path, index=False)
    completed = subprocess.run([sys.executable, str(RUNNER), "--input-csv", str(path), "--output-dir", str(destination)],
                               cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "Missing requested symbols" in completed.stderr
    assert not destination.exists()
