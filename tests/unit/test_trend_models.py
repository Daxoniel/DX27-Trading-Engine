from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from math import sqrt

import pandas as pd
import pytest

from dx27.intelligence.sentinel.research import trend_models as models
from dx27.intelligence.sentinel.research.trend_models import (
    CANDIDATES, TrendState, candidate_series, lean_ema, lean_rsi_14, qc_ewmstd, simple_returns,
)


def dates(count):
    return tuple(date(2019, 1, 1) + timedelta(days=i) for i in range(count))


def series(closes, candidate_id):
    return tuple(o for o in candidate_series("SPY", dates(len(closes)), closes) if o.candidate_id == candidate_id)


def test_lean_authoritative_ema_fixture_full_recursion():
    # Reproduces LEAN ExponentialMovingAverageTests fixture, not pandas EMA.
    values = [1, 10, 100, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000]
    actual = lean_ema(values, 4)
    assert actual[:3] == (None, None, None)
    assert actual[3] == 277.75
    assert actual[4] == pytest.approx(966.65)
    expected = 277.75
    for index in range(4, len(values)):
        expected = 0.4 * values[index] + 0.6 * expected
        assert actual[index] == pytest.approx(expected, rel=1e-14)


@pytest.mark.parametrize("period", [0, -1, 1.5, True])
def test_ema_invalid_period_rejected(period):
    with pytest.raises(ValueError):
        lean_ema([1, 2], period)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_ema_rejects_nonfinite_even_during_warmup(value):
    with pytest.raises(ValueError):
        lean_ema([1, value], 4)


def test_ema_period_one_and_empty_input():
    assert lean_ema([2, -3, 4], 1) == (2, -3, 4)
    assert lean_ema([], 4) == ()


def test_exact_candidate_definitions_and_classification():
    assert [(c.fast, c.slow) for c in CANDIDATES if c.family == "ewmac"] == [(8, 32), (16, 64), (32, 128), (64, 256)]
    assert [c.horizon for c in CANDIDATES if c.family == "tsmom"] == [21, 63, 126, 252]
    assert [c.candidate_id for c in CANDIDATES if c.sensitivity_only] == ["ewmac_8_32", "tsmom_21", "tsmom_63", "tsmom_126"]
    cross = CANDIDATES[-1]
    assert (cross.candidate_id, cross.fast, cross.slow, cross.source_classification) == (
        "lean_ema_cross_12_26", 12, 26, "LEAN_VERIFIED")
    assert all(c.source_classification == "QC_RESEARCH_REPRODUCTION" for c in CANDIDATES[1:4])
    assert all(c.source_classification == "DX27_RESEARCH_DEFINITION" for c in CANDIDATES[4:8])


@pytest.mark.parametrize("closes,expected", [
    ([100 + i for i in range(30)], TrendState.BULLISH),
    ([100 - i for i in range(30)], TrendState.BEARISH),
    ([100] * 30, TrendState.NEUTRAL),
])
def test_lean_cross_exact_sign_and_readiness(closes, expected):
    observations = series(closes, "lean_ema_cross_12_26")
    assert all(o.state is None and not o.is_ready for o in observations[:25])
    assert observations[25].state == expected
    assert observations[-1].state == expected
    assert observations[-1].primary_value == lean_ema(closes, 12)[-1] - lean_ema(closes, 26)[-1]
    assert all(o.normalized_score is None for o in observations)


def test_simple_returns_not_logarithmic():
    assert simple_returns([100, 110, 99]) == pytest.approx((None, 0.1, -0.1), nan_ok=True)


def test_ewmstd_exact_pandas_reference_and_warmup():
    closes = [100 + i * 0.3 + (i % 7) for i in range(90)]
    returns = pd.Series([float("nan")] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))])
    reference = returns.ewm(span=32, min_periods=32, adjust=True).std(bias=False)
    actual = qc_ewmstd(closes)
    assert actual[:32] == (None,) * 32
    assert actual[32] is not None
    for got, expected in zip(actual[32:], reference[32:]):
        assert got == pytest.approx(expected, rel=1e-14)
    # These alternatives must not accidentally reproduce this reference.
    assert actual[-1] != pytest.approx(returns.ewm(span=32, min_periods=32, adjust=False).std(bias=False).iloc[-1], rel=1e-8)
    assert actual[-1] != pytest.approx(returns.ewm(span=32, min_periods=32, adjust=True).std(bias=True).iloc[-1], rel=1e-8)


def test_ewmstd_zero_is_not_floored():
    assert qc_ewmstd([100] * 40) == (None,) * 32 + (0.0,) * 8
    for candidate in CANDIDATES[:4]:
        observations = series([100] * 300, candidate.candidate_id)
        assert observations[-1].primary_value == 0
        assert observations[-1].sigma_daily == 0
        assert observations[-1].state is None
        assert observations[-1].normalized_score is None


@pytest.mark.parametrize("candidate", CANDIDATES[:4], ids=lambda c: c.candidate_id)
@pytest.mark.parametrize("direction", [1, -1])
def test_ewmac_exact_denominator_sign_and_first_ready(candidate, direction):
    closes = [500 + direction * (i * 0.5 + i % 3) for i in range(300)]
    observations = series(closes, candidate.candidate_id)
    ready_index = max(candidate.slow - 1, 32)
    assert all(o.state is None for o in observations[:ready_index])
    assert observations[ready_index].is_ready
    final = observations[-1]
    raw = lean_ema(closes, candidate.fast)[-1] - lean_ema(closes, candidate.slow)[-1]
    assert final.primary_value == raw
    assert final.normalized_score == raw / (closes[-1] * qc_ewmstd(closes)[-1])
    assert final.state == TrendState(direction)


@pytest.mark.parametrize("spread,state", [(0, TrendState.NEUTRAL), (1e-12, TrendState.BULLISH), (-1e-12, TrendState.BEARISH)])
def test_ewmac_no_neutral_band_or_threshold(monkeypatch, spread, state):
    # Isolate the final algebra, including an exactly zero spread with sigma>0.
    monkeypatch.setattr(models, "lean_ema", lambda values, period: (spread if period == 8 else 0.0,) * len(values))
    monkeypatch.setattr(models, "qc_ewmstd", lambda values: (0.001,) * len(values))
    observed = series([100] * 35, "ewmac_8_32")[-1]
    assert observed.normalized_score == spread / (100 * 0.001)
    assert observed.state == state


@pytest.mark.parametrize("horizon", [21, 63, 126, 252])
def test_tsmom_raw_return_and_exact_readiness(horizon):
    closes = [100 + i + i % 2 for i in range(horizon + 2)]
    observations = series(closes, f"tsmom_{horizon}")
    assert all(o.state is None for o in observations[:horizon])
    first = observations[horizon]
    assert first.primary_value == closes[horizon] / closes[0] - 1
    assert first.state == TrendState.BULLISH
    if horizon < 32:
        assert first.normalized_score is None
    else:
        assert first.normalized_score == first.primary_value / (first.sigma_daily * sqrt(horizon))


@pytest.mark.parametrize("closes,state", [([100] * 260, TrendState.NEUTRAL), ([1000 - i for i in range(260)], TrendState.BEARISH)])
def test_tsmom_state_independent_of_normalized_diagnostic(monkeypatch, closes, state):
    monkeypatch.setattr(models, "qc_ewmstd", lambda values: (None,) * len(values))
    for candidate in CANDIDATES[4:8]:
        observation = series(closes, candidate.candidate_id)[-1]
        assert observation.state == state
        assert observation.normalized_score is None
    monkeypatch.setattr(models, "qc_ewmstd", lambda values: (0.0,) * len(values))
    assert series(closes, "tsmom_252")[-1].state == state
    assert series(closes, "tsmom_252")[-1].normalized_score is None


def test_rsi_wilder_seed_and_full_recursion():
    closes = [100, 101, 99, 103, 102, 104, 100, 105, 104, 107, 102, 106, 105, 108, 104, 110, 109, 111]
    actual = lean_rsi_14(closes)
    assert actual[:14] == (None,) * 14
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in deltas[:14]) / 14
    loss = sum(max(-d, 0) for d in deltas[:14]) / 14
    assert actual[14] == pytest.approx(100 - 100 / (1 + gain / loss))
    for index in range(15, len(closes)):
        gain = (13 * gain + max(deltas[index - 1], 0)) / 14
        loss = (13 * loss + max(-deltas[index - 1], 0)) / 14
        assert actual[index] == pytest.approx(100 - 100 / (1 + gain / loss))


@pytest.mark.parametrize("closes,expected", [([100] * 16, 100), (list(range(100, 116)), 100), (list(range(116, 100, -1)), 0), ([100 - i * 1e-12 for i in range(16)], 100)])
def test_rsi_zero_loss_rounding_and_warmup(closes, expected):
    actual = lean_rsi_14(closes)
    assert actual[:14] == (None,) * 14
    assert actual[14:] == (expected, expected)


def test_rsi_is_passive_and_observations_are_immutable(monkeypatch):
    closes = [100 + i * 0.1 + i % 9 for i in range(300)]
    baseline = candidate_series("SPY", dates(300), closes)
    monkeypatch.setattr(models, "lean_rsi_14", lambda values: (0.0,) * len(values))
    changed = candidate_series("SPY", dates(300), closes)
    assert [(o.state, o.primary_value, o.normalized_score) for o in changed] == [
        (o.state, o.primary_value, o.normalized_score) for o in baseline]
    assert all(o.rsi_14 == 0 and o.diagnostics["rsi_14"] == 0 for o in changed)
    with pytest.raises(FrozenInstanceError):
        changed[-1].state = TrendState.NEUTRAL
    with pytest.raises(TypeError):
        changed[-1].diagnostics["rsi_14"] = 100
