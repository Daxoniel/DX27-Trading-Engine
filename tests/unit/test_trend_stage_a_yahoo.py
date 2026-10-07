"""Deterministic provider mocks and frozen tournament integration."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stage_a", ROOT / "runners/standalone/trend_stage_a_yahoo.py")
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


@pytest.fixture
def histories():
    dates = pd.bdate_range("2003-01-01", periods=256).append(
        pd.DatetimeIndex(["2005-01-03", "2019-12-31", "2020-01-02", "2026-09-30"]))
    output = {}
    for symbol in a.STAGE_A_SYMBOLS:
        index = dates if symbol != "GLD" else dates[-5:]
        close = [100 + (i % 17) / 10 for i in range(len(index))]
        output[symbol] = pd.DataFrame(dict(Open=close, High=[c + 1 for c in close],
                                          Low=[c - 1 for c in close], Close=close,
                                          Volume=range(len(index))), index=index)
    return output


@pytest.fixture
def frame(histories):
    return pd.concat([a.normalize_symbol(s, h) for s, h in histories.items()], ignore_index=True)


def mock_provider(monkeypatch, histories):
    calls = []
    def ticker(symbol):
        calls.append(symbol)
        obj = Mock()
        def history(**kwargs):
            assert kwargs == dict(start="2003-01-01", end="2026-10-01", interval="1d",
                                  auto_adjust=True, back_adjust=False, actions=False,
                                  repair=False, keepna=False, rounding=False, raise_errors=True)
            return histories[symbol]
        obj.history.side_effect = history
        return obj
    monkeypatch.setattr(a.yfinance, "Ticker", ticker)
    return calls


def test_exact_sequential_provider_contract_and_unchanged_prices(monkeypatch, histories):
    for h in histories.values():
        h["Adj Close"] = 999999.0
    calls = mock_provider(monkeypatch, histories)
    data, coverage = a.acquire_data()
    assert calls == list(a.STAGE_A_SYMBOLS)
    assert list(data.columns) == list(a.REQUIRED_COLUMNS)
    assert list(data[["symbol", "date"]].itertuples(index=False, name=None)) == sorted(
        data[["symbol", "date"]].itertuples(index=False, name=None))
    for s, h in histories.items():
        assert data[data.symbol == s].close.tolist() == h.Close.tolist()
        assert data[data.symbol == s].volume.tolist() == h.Volume.tolist()
    assert coverage["GLD"]["rows_before_2005"] == 1


@pytest.mark.parametrize("column", ["Open", "High", "Low", "Close", "Volume"])
def test_missing_columns(histories, column):
    with pytest.raises(a.StageADataError):
        a.normalize_symbol("SPY", histories["SPY"].drop(columns=column))


@pytest.mark.parametrize("timezone", [None, "Asia/Tokyo", "America/New_York"])
def test_original_session_calendar_date(histories, timezone):
    h = histories["SPY"].iloc[:1].copy()
    h.index = pd.DatetimeIndex(["2026-09-30"]).tz_localize(timezone)
    assert a.normalize_symbol("SPY", h).date.tolist() == ["2026-09-30"]


@pytest.mark.parametrize("column,value", [("open", float("nan")), ("high", float("inf")),
    ("low", -1), ("close", 0), ("volume", -1), ("high", 1), ("low", 200)])
def test_invalid_numeric_and_ohlc(frame, column, value):
    frame.loc[0, column] = value
    with pytest.raises(a.StageADataError):
        a.validate_data(frame)


@pytest.mark.parametrize("case", ["duplicate", "universe", "last_date", "warmup", "selection", "late"])
def test_coverage_fails_closed(frame, case):
    if case == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif case == "universe":
        frame = frame[frame.symbol != "QQQ"]
    elif case == "last_date":
        frame = frame[~((frame.symbol == "SPY") & (frame.date == "2026-09-30"))]
    elif case == "warmup":
        frame = frame.drop(index=0)
    elif case == "selection":
        frame = frame[~((frame.symbol == "SPY") & frame.date.between("2005-01-01", "2019-12-31"))]
    else:
        frame.loc[0, "date"] = "2026-10-01"
    with pytest.raises(a.StageADataError):
        a.validate_data(frame)


def test_gld_warmup_exception(frame):
    assert a.validate_data(frame)["GLD"]["rows_before_2005"] == 1


@pytest.mark.parametrize("succeed", [True, False])
def test_bounded_retries(monkeypatch, histories, succeed):
    error = TimeoutError("transient")
    history = Mock(side_effect=[error, error, histories["SPY"] if succeed else error])
    monkeypatch.setattr(a.yfinance, "Ticker", Mock(return_value=Mock(history=history)))
    waits = Mock()
    monkeypatch.setattr(a.time, "sleep", waits)
    if succeed:
        assert a.fetch_symbol("SPY") is histories["SPY"]
    else:
        with pytest.raises(a.StageADataError, match="SPY: TimeoutError: transient"):
            a.fetch_symbol("SPY")
    assert history.call_count == 3
    assert [c.args[0] for c in waits.call_args_list] == [2, 5]


def test_failed_symbol_stops_dataset(monkeypatch, histories):
    calls = []
    def fetch(symbol):
        calls.append(symbol)
        if symbol == "QQQ":
            raise a.StageADataError("QQQ failure")
        return histories[symbol]
    monkeypatch.setattr(a, "fetch_symbol", fetch)
    with pytest.raises(a.StageADataError, match="QQQ"):
        a.acquire_data()
    assert calls == ["SPY", "QQQ"]


def test_full_offline_execution_repeatability_and_hashes(monkeypatch, histories, tmp_path, capsys):
    mock_provider(monkeypatch, histories)
    runner = Mock(wraps=a.run_tournament)
    monkeypatch.setattr(a, "run_tournament", runner)
    a.run_stage_a(tmp_path)
    assert len(runner.call_args.args) == 1 and not runner.call_args.kwargs
    first = {n: (tmp_path / n).read_bytes() for n in (*a.ARTIFACTS, "stage_a_artifact_hashes.json")}
    a.run_stage_a(tmp_path)
    assert first == {n: (tmp_path / n).read_bytes() for n in first}
    digest = json.loads(first["stage_a_artifact_hashes.json"])
    assert digest == {n: a.sha256(tmp_path / n) for n in a.ARTIFACTS}
    manifest = json.loads(first["stage_a_data_manifest.json"])
    assert manifest["adjustment_method"] == "yfinance_history_auto_adjust_true"
    assert manifest["csv_sha256"] == digest["stage_a_adjusted_daily.csv"]
    assert "timestamp" not in manifest and str(tmp_path) not in first["stage_a_data_manifest.json"].decode()
    for name, count in [("stage_a_aggregate.csv", 18), ("stage_a_selection_oos_delta.csv", 9),
                        ("stage_a_sensitivity_aggregate.csv", 24)]:
        data = pd.read_csv(tmp_path / name)
        assert len(data) == count
        assert not {"winner", "rank", "score", "quality"} & set(data.columns)
    output = capsys.readouterr().out
    assert "DATA COVERAGE" in output and "OUT-OF-SAMPLE 2020-2026-09-30" in output
    aggregate = pd.read_csv(tmp_path / "stage_a_aggregate.csv")
    assert aggregate[aggregate.split == "selection"].candidate_id.tolist() == list(a.CANDIDATE_IDS)


@pytest.mark.parametrize("artifact", [*a.OUTPUT_FILENAMES, "research_id", "winner_selected", "production_trend_detector_created"])
def test_tournament_sanity_failures(monkeypatch, histories, tmp_path, artifact):
    mock_provider(monkeypatch, histories)
    a.run_stage_a(tmp_path)
    directory = tmp_path / "tournament"
    if artifact.endswith(".csv"):
        p = directory / artifact
        p.write_text(p.read_text().splitlines()[0] + "\n")
    else:
        p = directory / a.OUTPUT_FILENAMES[-1]
        summary = json.loads(p.read_text())
        key = artifact if not artifact.endswith(".json") else "research_id"
        summary[key] = "invalid"
        p.write_text(json.dumps(summary))
    with pytest.raises(a.StageAResearchError):
        a.check_tournament(directory, sum(len(h) for h in histories.values()))


def test_aggregate_arithmetic_and_delta(monkeypatch, histories, tmp_path):
    mock_provider(monkeypatch, histories)
    a.run_stage_a(tmp_path)
    metrics = pd.read_csv(tmp_path / "tournament/trend_metrics.csv")
    for split, offset in [("selection", 0), ("out_of_sample", 1)]:
        mask = metrics.split == split
        for name in ["evaluated_days", "transitions", "transition_rate_per_252", "persistence_median",
                     "mfe_20_median", "mae_20_median", "mfe_60_median", "mae_60_median"]:
            metrics.loc[mask, name] = list(range(1 + offset, 14 + offset)) * 9
        for prefix, source, horizons in [("false_reversal", "false_reversal_rate", (5,10,20)),
                                         ("directional", "directional_consistency", (5,10,20,60))]:
            for n in horizons:
                metrics.loc[mask, f"eligible_{prefix}_{n}"] = 4
                metrics.loc[mask, f"{source}_{n}"] = .25 + .25 * offset
    aggregate = a.aggregate_metrics(metrics)
    row = aggregate.iloc[0]
    group = metrics[(metrics.split == "selection") & (metrics.candidate_id == a.CANDIDATE_IDS[0])]
    assert row.evaluated_days_total == group.evaluated_days.sum()
    assert row.transitions_total == group.transitions.sum()
    assert row.persistence_symbol_p25 == group.persistence_median.quantile(.25, interpolation="linear")
    assert row.persistence_symbol_p75 == group.persistence_median.quantile(.75, interpolation="linear")
    assert row.mfe_20_symbol_median == group.mfe_20_median.median()
    assert row.false_reversal_10_weighted == .25
    assert row.directional_60_weighted == .25
    delta = a.selection_oos_delta(aggregate)
    assert (delta.false_reversal_10_weighted == .25).all()
    assert (delta.directional_60_weighted == .25).all()
    assert (delta.evaluated_days_total == 13).all()


def test_weighted_unequal_denominators_and_nulls():
    group = pd.DataFrame(dict(rate=[.5, .25, float("nan")], eligible=[2, 4, 0]))
    assert a.weighted(group, "rate", "eligible") == (6, 2 / 6)
    assert a.weighted(group.iloc[-1:], "rate", "eligible") == (0, None)
    group.loc[0, "rate"] = .3
    with pytest.raises(a.StageAResearchError):
        a.weighted(group, "rate", "eligible")


def test_sensitivity_linear_quartiles(monkeypatch, histories, tmp_path):
    mock_provider(monkeypatch, histories)
    a.run_stage_a(tmp_path)
    sensitivity = pd.read_csv(tmp_path / "tournament/trend_sensitivity.csv")
    sensitivity["state_agreement"] = [i / 312 for i in range(312)]
    sensitivity["transition_jaccard_3"] = sensitivity.state_agreement
    output = a.aggregate_sensitivity(sensitivity)
    for _, row in output.iterrows():
        group = sensitivity[(sensitivity.split == row.split) & (sensitivity.family == row.family)
                            & (sensitivity.candidate_a == row.candidate_a) & (sensitivity.candidate_b == row.candidate_b)]
        assert row.symbols == 13
        assert row.state_agreement_symbol_p25 == group.state_agreement.quantile(.25, interpolation="linear")
        assert row.transition_jaccard_3_symbol_p75 == group.transition_jaccard_3.quantile(.75, interpolation="linear")


@pytest.mark.parametrize("path", [ROOT, ROOT / "research", ROOT / "nonexistent/output"])
def test_repository_destination_rejected(monkeypatch, path):
    acquire = Mock()
    monkeypatch.setattr(a, "acquire_data", acquire)
    with pytest.raises(a.StageADataError, match="outside"):
        a.run_stage_a(path)
    acquire.assert_not_called()


def test_symlink_repository_destination_rejected(tmp_path):
    (tmp_path / "tournament").symlink_to(ROOT, target_is_directory=True)
    with pytest.raises(a.StageADataError):
        a.output_directory(tmp_path)
