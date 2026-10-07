"""DX27_RESEARCH_DEFINITION state/event metrics; forward data stays here.

All horizons and transition tolerances use observed bars, not calendar days.
Split evaluation retains the prior state for boundary transition detection,
but clips persistence and all forward windows to the split/dataset boundary.
"""

from dataclasses import dataclass
from datetime import date
from itertools import combinations
from statistics import mean, median
from types import MappingProxyType
from typing import Mapping, Sequence

import pandas as pd

from .trend_models import CANDIDATES, TrendObservation, TrendState


@dataclass(frozen=True)
class DateSplit:
    name: str
    start: date
    end: date


# DX27_RESEARCH_PROTOCOL, not source-model parameters.
SPLITS = (
    DateSplit("selection", date(2005, 1, 1), date(2019, 12, 31)),
    DateSplit("out_of_sample", date(2020, 1, 1), date(2026, 9, 30)),
)
DIRECTIONAL = frozenset((TrendState.BEARISH, TrendState.BULLISH))


@dataclass(frozen=True)
class MetricRow:
    split: str
    symbol: str
    candidate_id: str
    family: str
    values: Mapping[str, float | int | None]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def as_dict(self) -> dict[str, str | float | int | None]:
        return dict(split=self.split, symbol=self.symbol, candidate_id=self.candidate_id,
                    family=self.family, **self.values)


@dataclass(frozen=True)
class SensitivityRow:
    split: str
    symbol: str
    family: str
    candidate_a: str
    candidate_b: str
    common_evaluated_dates: int
    state_agreement: float | None
    transitions_a: int
    transitions_b: int
    transition_match_count: int
    transition_jaccard_3: float | None


def directional_transitions(states: Sequence[TrendState | None]) -> tuple[int, ...]:
    return tuple(i for i in range(1, len(states))
                 if states[i - 1] in DIRECTIONAL and states[i] in DIRECTIONAL
                 and states[i] != states[i - 1])


def persistence_lengths(states: Sequence[TrendState | None]) -> tuple[int, ...]:
    runs: list[int] = []
    previous = None
    length = 0
    for state in states:
        if state in DIRECTIONAL and state == previous:
            length += 1
        else:
            if length:
                runs.append(length)
            length = 1 if state in DIRECTIONAL else 0
        previous = state
    if length:
        runs.append(length)
    return tuple(runs)


def state_agreement(
    a: Sequence[TrendState | None], b: Sequence[TrendState | None],
) -> tuple[int, float | None]:
    if len(a) != len(b):
        raise ValueError("State series must share aligned observed dates")
    common = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    return len(common), sum(x == y for x, y in common) / len(common) if common else None


def match_transitions(a: Sequence[int], b: Sequence[int]) -> tuple[tuple[int, int], ...]:
    """DX27_RESEARCH_DEFINITION: greedy +/-3 observed-bar matching.

    Ascending A, nearest unused B, ties to earlier B. No directional voting.
    Inputs are positions on the same symbol's observed-bar date axis.
    """
    unused = set(b)
    matches = []
    for position in sorted(a):
        eligible = [other for other in unused if abs(position - other) <= 3]
        if eligible:
            other = min(eligible, key=lambda value: (abs(position - value), value))
            matches.append((position, other))
            unused.remove(other)
    return tuple(matches)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _moments(values: Sequence[float]) -> tuple[float | None, float | None]:
    return (mean(values), median(values)) if values else (None, None)


def evaluate_metrics(
    observations: Sequence[TrendObservation], closes: Sequence[float], split: DateSplit,
) -> MetricRow:
    """Evaluate a single symbol/configuration after its complete state series.

    False reversal uses next N available (non-None) candidate observations;
    forward close horizons use N observed input bars. Neutral is available.
    Neither window crosses the split end. No forward data is added to models.
    """
    if not observations or len(observations) != len(closes):
        raise ValueError("Nonempty aligned observations and closes required")
    first = observations[0]
    if any((o.symbol, o.candidate_id) != (first.symbol, first.candidate_id) for o in observations):
        raise ValueError("Metrics require a single symbol and candidate")
    if any(a.date >= b.date for a, b in zip(observations, observations[1:])):
        raise ValueError("Observations must be strictly ascending")
    states = tuple(o.state for o in observations)
    indices = [i for i, o in enumerate(observations) if split.start <= o.date <= split.end]
    selected = set(indices)
    transitions = [i for i in directional_transitions(states) if i in selected]
    days = sum(states[i] is not None for i in indices)
    runs = persistence_lengths([states[i] for i in indices])
    values: dict[str, int | float | None] = {
        "evaluated_days": days,
        "transitions": len(transitions),
        "transition_rate_per_252": len(transitions) / days * 252 if days else None,
        "persistence_count": len(runs) if runs else None,
        "persistence_mean": mean(runs) if runs else None,
        "persistence_median": median(runs) if runs else None,
        # Standard sample quartiles (pandas linear interpolation).
        "persistence_p25": float(pd.Series(runs).quantile(0.25)) if runs else None,
        "persistence_p75": float(pd.Series(runs).quantile(0.75)) if runs else None,
    }
    available = [i for i in indices if states[i] is not None]
    available_positions = {index: position for position, index in enumerate(available)}
    for horizon in (5, 10, 20):
        eligible = false = 0
        for index in transitions:
            position = available_positions[index]
            future = available[position + 1:position + horizon + 1]
            if len(future) == horizon:
                eligible += 1
                false += any(states[i] == states[index - 1] for i in future)
        values[f"eligible_false_reversal_{horizon}"] = eligible
        values[f"false_reversal_rate_{horizon}"] = _ratio(false, eligible)
    for horizon in (5, 10, 20, 60):
        eligible = consistent = 0
        mfes: list[float] = []
        maes: list[float] = []
        for index in transitions:
            if index + horizon not in selected:
                continue
            eligible += 1
            direction = int(states[index])
            forward = direction * (closes[index + horizon] / closes[index] - 1)
            consistent += forward > 0
            if horizon in (20, 60):
                directional = [direction * (closes[i] / closes[index] - 1)
                               for i in range(index + 1, index + horizon + 1)]
                mfes.append(max(directional))
                maes.append(min(directional))
        values[f"eligible_directional_{horizon}"] = eligible
        values[f"directional_consistency_{horizon}"] = _ratio(consistent, eligible)
        if horizon in (20, 60):
            values[f"mfe_{horizon}_mean"], values[f"mfe_{horizon}_median"] = _moments(mfes)
            values[f"mae_{horizon}_mean"], values[f"mae_{horizon}_median"] = _moments(maes)
    return MetricRow(split.name, first.symbol, first.candidate_id, first.family, values)


def evaluate_sensitivity(
    series: Mapping[str, Sequence[TrendObservation]], split: DateSplit,
) -> tuple[SensitivityRow, ...]:
    """Pairwise evidence within each family, on one common symbol/date axis."""
    rows = []
    for family in ("ewmac", "tsmom"):
        ids = sorted(c.candidate_id for c in CANDIDATES if c.family == family)
        for a, b in combinations(ids, 2):
            left, right = series[a], series[b]
            if not left or [(o.symbol, o.date) for o in left] != [(o.symbol, o.date) for o in right]:
                raise ValueError("Sensitivity requires aligned single-symbol dates")
            if len({o.symbol for o in left}) != 1:
                raise ValueError("Sensitivity requires one symbol")
            indices = [i for i, o in enumerate(left) if split.start <= o.date <= split.end]
            selected = set(indices)
            states_a, states_b = [o.state for o in left], [o.state for o in right]
            common, agreement = state_agreement([states_a[i] for i in indices], [states_b[i] for i in indices])
            transitions_a = [i for i in directional_transitions(states_a) if i in selected]
            transitions_b = [i for i in directional_transitions(states_b) if i in selected]
            matched = len(match_transitions(transitions_a, transitions_b))
            rows.append(SensitivityRow(
                split.name, left[0].symbol, family, a, b, common, agreement,
                len(transitions_a), len(transitions_b), matched,
                _ratio(matched, len(transitions_a) + len(transitions_b) - matched),
            ))
    return tuple(sorted(rows, key=lambda r: (r.split, r.symbol, r.family, r.candidate_a, r.candidate_b)))
