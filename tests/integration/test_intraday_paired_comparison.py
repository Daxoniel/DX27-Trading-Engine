"""Paired statistics and fail-closed study boundaries; no vendor calls."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dx27.adapters.intraday.cli import create_demo
from dx27.adapters.intraday.data import IntradayDataset, load_csv
from dx27.adapters.intraday.paired_comparison import (
    compare_results, load_protocol, paired_interval, run_comparison, runtime, validate_dataset,
)

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "docs/research/intra-1c/q2-2025-protocol.json"
SHA = "62731c4e45200b689d099da1acb5b5309d817b9bfe1e35bb5b370343dd266a17"


def protocol():
    return json.loads(PROTOCOL.read_text())


def toy(returns):
    p = protocol()
    p["baseline_config"]["initial_cash"] = 100.0
    p["data"]["expected_evaluation_sessions"] = len(returns)
    p["analysis"]["bootstrap"].update(block_sessions=min(2, len(returns)), resamples=100)
    daily, previous = [], 100.0
    for i, value in enumerate(returns):
        ending = previous * (1 + value)
        daily.append(dict(session=f"2025-04-{i+1:02d}", starting_equity=previous,
                          ending_equity=ending, data_complete=True, open_positions=0))
        previous = ending
    summary = dict(status="COMPLETE_REPLAY", open_positions=0, performance_admissible=True,
                   ending_cash=previous, ending_equity=previous, net_pnl=previous-100,
                   config=p["baseline_config"], input=dict(csv_sha256="same-source"), calendar_version="same-calendar")
    result = SimpleNamespace(summary=summary, daily=daily,
                             fills=[dict(cash_delta=previous-100)], trades=[dict(net_pnl=previous-100)], equity=[])
    return p, result


def pair(a, b):
    p, baseline = toy(a)
    _, filtered = toy(b)
    filtered.summary["config"] = dict(p["baseline_config"], opening_volume=p["rvol"])
    return p, baseline, filtered


def test_paired_bootstrap_identical_paths_remain_zero_and_reproducible():
    values = [0, .01, -.02, 0, .03, -.01]
    kwargs = dict(block_sessions=5, resamples=300, seed=42)
    assert paired_interval(values, values, **kwargs) == [0, 0]
    first = paired_interval(values, [v/2 for v in values], **kwargs)
    assert first == paired_interval(values, [v/2 for v in values], **kwargs)


def test_compounded_constant_return_interval_and_primary_match():
    p, a, b = pair([0, 0, 0], [.01, .01, .01])
    summary, rows = compare_results(a, b, p)
    expected = ((1.01**3)-1)*100
    assert summary["primary_delta_net_return_pp"] == pytest.approx(expected)
    assert summary["paired_bootstrap_95_interval_pp"] == pytest.approx([expected, expected])
    assert len(rows) == 3 and all(r["baseline_return"] == 0 for r in rows)
    assert not summary["execution_enabled"] and summary["effectiveness"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("kwargs", [dict(block_sessions=0), dict(resamples=True), dict(seed=-1)])
def test_invalid_bootstrap_limits(kwargs):
    args = dict(block_sessions=1, resamples=100, seed=42); args.update(kwargs)
    with pytest.raises(ValueError):
        paired_interval([0, 0], [0, 0], **args)


def test_daily_returns_cannot_be_misaligned_or_nonfinite():
    with pytest.raises(ValueError):
        paired_interval([0], [0, 0], block_sessions=1, resamples=1, seed=1)
    with pytest.raises(ValueError):
        paired_interval([float("nan")], [0], block_sessions=1, resamples=1, seed=1)


@pytest.mark.parametrize("field,value", [("status", "INCOMPLETE"), ("open_positions", 1), ("performance_admissible", False)])
def test_one_invalid_arm_blocks_both_without_dropping_days(field, value):
    p, a, b = pair([.01, 0], [0, .01]); b.summary[field] = value
    summary, rows = compare_results(a, b, p)
    assert summary["primary_delta_net_return_pp"] is None
    assert summary["paired_bootstrap_95_interval_pp"] is None and rows == []


def test_accounting_residual_above_absolute_tolerance_is_rejected():
    p, a, b = pair([0, .01], [0, 0])
    a.fills[0]["cash_delta"] += .00001
    with pytest.raises(ValueError, match="ACCOUNTING"):
        compare_results(a, b, p)


def test_source_config_and_session_mismatches_are_rejected():
    for mutate, code in [
        (lambda b: b.summary["input"].update(csv_sha256="other"), "CONFIGURATION_OR_SOURCE"),
        (lambda b: b.summary["config"].update(adx_threshold=26), "CONFIGURATION_OR_SOURCE"),
        (lambda b: b.daily[0].update(session="2025-04-09"), "SESSION_MISMATCH"),
        (lambda b: b.daily[0].update(starting_equity=99), "EQUITY_CHAIN"),
    ]:
        p, a, b = pair([0, 0], [0, 0]); mutate(b)
        with pytest.raises(ValueError, match=code):
            compare_results(a, b, p)


def test_registered_protocol_and_runtime_source_seals(tmp_path):
    if protocol()["runtime"] != runtime():
        # CI uses a different Python/dependency environment from the real study.
        with pytest.raises(ValueError, match="RUNTIME_CHANGED"):
            load_protocol(PROTOCOL, SHA)
    else:
        assert load_protocol(PROTOCOL, SHA)[0]["study_id"] == "intra-1c-2025-q2-v1"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        load_protocol(PROTOCOL, "0"*64)
    p = protocol(); p["engine_files"][next(iter(p["engine_files"]))] = "0"*64
    path = tmp_path / "changed.json"; path.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="ENGINE_CHANGED"):
        load_protocol(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_data_capture_uses_timestamp_precision_and_declared_calendar(tmp_path):
    path = tmp_path / "demo.csv"; create_demo(path)
    data = load_csv(path)
    p = protocol()
    p["data"].update(start="2025-11-26T00:00:00Z", end_exclusive="2025-11-29T00:00:00Z",
                     evaluation_start="2025-11-28", evaluation_end_exclusive="2025-11-29",
                     expected_context_sessions=2, expected_evaluation_sessions=1)
    metadata = dict(p["data"], csv_sha256=data.provenance["csv_sha256"], raw_sha256="fixture-only",
                    retrieved_started_at="2030-01-01T00:00:00.123456Z")
    declared_fixture = IntradayDataset(data.bars, metadata)
    validate_dataset(declared_fixture, p)
    metadata["retrieved_started_at"] = "2020-01-01T00:00:00.123456Z"
    with pytest.raises(ValueError, match="PRECEDES_REGISTRATION"):
        validate_dataset(IntradayDataset(data.bars, metadata), p)
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        validate_dataset(data, p)  # Synthetic source cannot become market evidence.


def test_synthetic_or_existing_output_rejected_before_writing_results(tmp_path):
    p = protocol(); p["runtime"] = runtime()
    file = tmp_path / "protocol.json"; file.write_text(json.dumps(p))
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    data = tmp_path / "demo.csv"; create_demo(data)
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        run_comparison(file, sha, data, output)
    assert not output.exists()
    output.mkdir()
    with pytest.raises(ValueError, match="OUTPUT_ALREADY_EXISTS"):
        run_comparison(file, sha, data, output)
