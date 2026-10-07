"""Close-only trend measurements, with no evaluator or production dependencies.

Sources: QuantConnect LEAN EMA.cs / EMA tests, EmaCrossAlphaModel (Daily
12/26), and RelativeStrengthIndex.cs; QC Research 16001, Combined Carry and
Trend, and 15875, Futures Fast Trend Following, with Trend Strength; MOP
(2012), JFE 104(2), DOI 10.1016/j.jfineco.2011.11.003.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum
from math import isfinite, sqrt
from types import MappingProxyType
from typing import Mapping, Sequence

import pandas as pd


class TrendState(IntEnum):
    BEARISH = -1
    NEUTRAL = 0
    BULLISH = 1


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    source_classification: str
    sensitivity_only: bool
    fast: int | None = None
    slow: int | None = None
    horizon: int | None = None


# QC_RESEARCH_REPRODUCTION: source spans 16/64, 32/128, 64/256.
# DX27_RESEARCH_DEFINITION: independent sensitivity-only 8/32, no blending.
# ACADEMIC: MOP supports 1–12 month persistence, not exact daily horizons.
# DX27_RESEARCH_DEFINITION: daily translations 21/63/126/252.
# LEAN_VERIFIED: directional Daily 12/26 baseline, without Insight behavior.
CANDIDATES = (
    Candidate("ewmac_8_32", "ewmac", "DX27_RESEARCH_DEFINITION", True, 8, 32),
    Candidate("ewmac_16_64", "ewmac", "QC_RESEARCH_REPRODUCTION", False, 16, 64),
    Candidate("ewmac_32_128", "ewmac", "QC_RESEARCH_REPRODUCTION", False, 32, 128),
    Candidate("ewmac_64_256", "ewmac", "QC_RESEARCH_REPRODUCTION", False, 64, 256),
    Candidate("tsmom_21", "tsmom", "DX27_RESEARCH_DEFINITION", True, horizon=21),
    Candidate("tsmom_63", "tsmom", "DX27_RESEARCH_DEFINITION", True, horizon=63),
    Candidate("tsmom_126", "tsmom", "DX27_RESEARCH_DEFINITION", True, horizon=126),
    Candidate("tsmom_252", "tsmom", "DX27_RESEARCH_DEFINITION", False, horizon=252),
    Candidate("lean_ema_cross_12_26", "lean_ema_cross", "LEAN_VERIFIED", False, 12, 26),
)


@dataclass(frozen=True)
class TrendObservation:
    symbol: str
    date: date
    candidate_id: str
    family: str
    state: TrendState | None
    primary_value: float | None
    normalized_score: float | None
    sigma_daily: float | None
    rsi_14: float | None
    is_ready: bool
    source_classification: str
    sensitivity_only: bool
    diagnostics: Mapping[str, float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Copy before freezing so callers cannot mutate a retained dict.
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def _finite_values(values: Sequence[float], *, positive: bool = False) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if any(not isfinite(value) or (positive and value <= 0) for value in result):
        raise ValueError("Samples must be finite" + (" and positive" if positive else ""))
    return result


def lean_ema(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    """LEAN_VERIFIED: unavailable until SMA seed, then alpha=2/(period+1)."""
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("EMA period must be an integer >= 1")
    samples = _finite_values(values)
    alpha = 2 / (period + 1)
    result: list[float | None] = []
    current: float | None = None
    for index, value in enumerate(samples):
        if index == period - 1:
            current = sum(samples[:period]) / period
        elif index >= period:
            assert current is not None
            current = alpha * value + (1 - alpha) * current
        result.append(current)
    return tuple(result)


def simple_returns(closes: Sequence[float]) -> tuple[float | None, ...]:
    """Simple close-to-close returns aligned with the original price bars."""
    values = _finite_values(closes, positive=True)
    if not values:
        return ()
    return (None,) + tuple(values[i] / values[i - 1] - 1 for i in range(1, len(values)))


def qc_ewmstd(closes: Sequence[float]) -> tuple[float | None, ...]:
    """QC_RESEARCH_REPRODUCTION: research 15875's exact EWMSTD operation.

    Explicit adjust=True and bias=False; 32 returns require 33 price bars.
    No epsilon or annualization. Zero volatility remains exactly zero.
    """
    returns = pd.Series(simple_returns(closes), dtype="float64")
    sigma = returns.ewm(span=32, min_periods=32, adjust=True).std(bias=False)
    return tuple(None if pd.isna(value) else float(value) for value in sigma)


def lean_rsi_14(closes: Sequence[float]) -> tuple[float | None, ...]:
    """LEAN_VERIFIED: RSI(14), SMA-seeded Wilder averages, 15-bar warm-up.

    LEAN's average-loss zero check rounds to 10 decimal places. Diagnostic
    only: no thresholds, slope rules, or effects on any candidate state.
    """
    values = _finite_values(closes, positive=True)
    result: list[float | None] = [None] * min(14, len(values))
    gains = [max(values[i] - values[i - 1], 0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0) for i in range(1, len(values))]
    avg_gain = avg_loss = 0.0
    for index in range(14, len(values)):
        if index == 14:
            avg_gain, avg_loss = sum(gains[:14]) / 14, sum(losses[:14]) / 14
        else:
            avg_gain = (13 * avg_gain + gains[index - 1]) / 14
            avg_loss = (13 * avg_loss + losses[index - 1]) / 14
        result.append(100.0 if round(avg_loss, 10) == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    return tuple(result)


def _state(value: float | None) -> TrendState | None:
    if value is None:
        return None
    return TrendState.BULLISH if value > 0 else TrendState.BEARISH if value < 0 else TrendState.NEUTRAL


def candidate_series(
    symbol: str, dates: Sequence[date], closes: Sequence[float],
) -> tuple[TrendObservation, ...]:
    """Produce all nine independent configurations for one ordered symbol.

    No forward-return argument or evaluator dependency exists. Each output
    uses only its prefix; RSI is passive extensible diagnostic metadata.
    """
    values = _finite_values(closes, positive=True)
    if len(dates) != len(values) or any(a >= b for a, b in zip(dates, dates[1:])):
        raise ValueError("Dates must be strictly ascending and aligned with closes")
    sigma, rsi = qc_ewmstd(values), lean_rsi_14(values)
    periods = {p for c in CANDIDATES for p in (c.fast, c.slow) if p is not None}
    emas = {period: lean_ema(values, period) for period in periods}
    observations = []
    for candidate in CANDIDATES:
        for index, close in enumerate(values):
            primary = normalized = None
            if candidate.horizon is not None:
                if index >= candidate.horizon:
                    primary = close / values[index - candidate.horizon] - 1
                    # DX27_RESEARCH_DEFINITION, diagnostic only, not a trigger.
                    if sigma[index] is not None and sigma[index] > 0:
                        normalized = primary / (sigma[index] * sqrt(candidate.horizon))
                state = _state(primary)
            else:
                fast, slow = emas[candidate.fast][index], emas[candidate.slow][index]
                if fast is not None and slow is not None:
                    primary = fast - slow
                if candidate.family == "ewmac":
                    # DX27_RESEARCH_DEFINITION, NOT an exact Carver forecast.
                    if primary is not None and sigma[index] is not None and sigma[index] > 0:
                        normalized = primary / (close * sigma[index])
                    state = _state(normalized)
                else:
                    state = _state(primary)
            observations.append(TrendObservation(
                symbol, dates[index], candidate.candidate_id, candidate.family,
                state, primary, normalized, sigma[index], rsi[index], state is not None,
                candidate.source_classification, candidate.sensitivity_only,
                {"rsi_14": rsi[index]},
            ))
    return tuple(sorted(observations, key=lambda o: (o.symbol, o.candidate_id, o.date)))
