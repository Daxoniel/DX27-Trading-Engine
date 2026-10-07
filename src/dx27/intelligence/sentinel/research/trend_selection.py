"""Pre-registered Stage-A research protocol; no acquisition or file IO.

DX27_RESEARCH_PROTOCOL: freeze before inspecting real tournament outputs.
Ranks use selection only to lock a provisional winner. OOS validates that
same candidate, never replaces it. Transition/persistence and sensitivity
remain diagnostics. This module creates no production detector or signals.
"""

import csv
import io
import json
from dataclasses import asdict, dataclass
from itertools import combinations
from math import isfinite
from statistics import mean, median
from typing import Sequence

import pandas as pd

from .trend_metrics import MetricRow, SensitivityRow, SPLITS
from .trend_models import CANDIDATES
from .trend_tournament import STAGE_A_SYMBOLS

PROTOCOL_ID = "dx27.trend.stage_a.selection.v0.1"
ELIGIBLE_IDS = tuple(c.candidate_id for c in CANDIDATES if not c.sensitivity_only)
EXCLUDED_IDS = tuple(c.candidate_id for c in CANDIDATES if c.sensitivity_only)
METRIC_DIRECTIONS = (
    ("false_reversal_rate_10", "lower"),
    ("false_reversal_rate_20", "lower"),
    ("directional_consistency_20", "higher"),
    ("directional_consistency_60", "higher"),
    ("mfe_60_median", "higher"),
    ("mae_60_median", "higher"),
)
DIAGNOSTICS = ("transition_rate_per_252", "persistence_median")
FAMILIES = {c.candidate_id: c.family for c in CANDIDATES}


@dataclass(frozen=True)
class PrimaryRank:
    split: str
    symbol: str
    metric: str
    candidate_id: str
    value: float | None
    rank: float


@dataclass(frozen=True)
class CandidateRanking:
    split: str
    candidate_id: str
    mean_primary_rank: float
    median_primary_rank: float
    p75_primary_rank: float
    number_of_metric_wins: int
    number_of_metric_losses: int
    false_reversal_rate_20_symbol_median: float | None
    directional_consistency_60_symbol_median: float | None
    mae_60_symbol_median: float | None
    transition_rate_per_252_symbol_median: float | None
    persistence_symbol_median: float | None


@dataclass(frozen=True)
class SensitivityDiagnostic:
    family: str
    candidate_a: str
    candidate_b: str
    selection_state_agreement_symbol_median: float | None
    oos_state_agreement_symbol_median: float | None
    state_agreement_delta_oos_minus_selection: float | None
    selection_transition_jaccard_3_symbol_median: float | None
    oos_transition_jaccard_3_symbol_median: float | None
    transition_jaccard_3_delta_oos_minus_selection: float | None


@dataclass(frozen=True)
class SelectionResult:
    selection_winner: str
    selection_rankings: tuple[CandidateRanking, ...]
    oos_validation_status: str
    oos_rankings: tuple[CandidateRanking, ...]
    sensitivity_diagnostics: tuple[SensitivityDiagnostic, ...]
    primary_ranks: tuple[PrimaryRank, ...]
    final_winner: str | None
    winner_selected: bool
    production_trend_detector_created: bool = False


def _value(value):
    """None/NaN are undefined; infinite or nonnumeric metrics fail closed."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Metric values must be numeric or undefined")
    if pd.isna(value):
        return None
    if not isfinite(value):
        raise ValueError("Infinite metric values are invalid")
    return float(value)


def _median(values):
    present = [v for v in values if v is not None]
    return median(present) if present else None


def _metric_index(rows):
    index = {}
    for row in rows:
        key = (row.split, row.symbol, row.candidate_id)
        if row.split not in {s.name for s in SPLITS} or row.symbol not in STAGE_A_SYMBOLS:
            raise ValueError("Unknown split or Stage-A symbol")
        if row.candidate_id not in FAMILIES or row.family != FAMILIES[row.candidate_id]:
            raise ValueError("Unknown candidate or inconsistent family")
        if key in index:
            raise ValueError("Duplicate split/symbol/candidate metrics")
        index[key] = row
    # Missing metric values receive rank 5; missing rows must never reduce
    # the fixed 13-symbol x 6-metric denominator for any eligible candidate.
    present_splits = {key[0] for key in index}
    if "selection" not in present_splits:
        raise ValueError("Selection metrics required")
    for split in present_splits:
        for symbol in STAGE_A_SYMBOLS:
            for candidate in ELIGIBLE_IDS:
                if (split, symbol, candidate) not in index:
                    raise ValueError("Complete eligible Stage-A metric rows required")
    return index, present_splits


def _tie_key(row):
    """Exact lexicographic tie-breaks; undefined medians sort worst."""
    def lower(value):
        return value if value is not None else float("inf")
    def higher(value):
        return -value if value is not None else float("inf")
    return (row.mean_primary_rank, row.p75_primary_rank,
            lower(row.false_reversal_rate_20_symbol_median),
            higher(row.directional_consistency_60_symbol_median),
            higher(row.mae_60_symbol_median), row.candidate_id)


def _rank_split(index, split):
    observations = []
    for symbol in sorted(STAGE_A_SYMBOLS):
        for metric, direction in METRIC_DIRECTIONS:
            values = [_value(index[split, symbol, c].values.get(metric)) for c in ELIGIBLE_IDS]
            ranks = pd.Series(values, dtype="float64").rank(
                method="average", ascending=direction == "lower", na_option="keep")
            for candidate, value, rank in zip(ELIGIBLE_IDS, values, ranks):
                observations.append(PrimaryRank(split, symbol, metric, candidate, value,
                                                5.0 if pd.isna(rank) else float(rank)))
    rankings = []
    for candidate in ELIGIBLE_IDS:
        ranks = [r.rank for r in observations if r.candidate_id == candidate]
        def across(metric):
            return _median([_value(index[split, s, candidate].values.get(metric)) for s in STAGE_A_SYMBOLS])
        rankings.append(CandidateRanking(
            split, candidate, mean(ranks), median(ranks),
            float(pd.Series(ranks).quantile(.75, interpolation="linear")),
            sum(r == 1 for r in ranks), sum(r == 5 for r in ranks),
            across("false_reversal_rate_20"), across("directional_consistency_60"),
            across("mae_60_median"), across(DIAGNOSTICS[0]), across(DIAGNOSTICS[1]),
        ))
    return tuple(sorted(rankings, key=_tie_key)), tuple(observations)


def oos_validation_status(mean_primary_rank):
    if not isfinite(mean_primary_rank) or not 1 <= mean_primary_rank <= 5:
        raise ValueError("OOS mean rank must be finite and between 1 and 5")
    if mean_primary_rank <= 2.5:
        return "PASS"
    if mean_primary_rank <= 3.0:
        return "WEAK_PASS"
    return "FAIL"


def _sensitivity(rows, metric_splits):
    if not rows:
        return ()
    pairs = tuple((family, a, b) for family in ("ewmac", "tsmom")
                  for a, b in combinations(sorted(c.candidate_id for c in CANDIDATES if c.family == family), 2))
    index = {}
    for row in rows:
        pair = (row.family, row.candidate_a, row.candidate_b)
        key = (row.split, row.symbol, *pair)
        if row.split not in metric_splits or row.symbol not in STAGE_A_SYMBOLS or pair not in pairs:
            raise ValueError("Unexpected sensitivity split/symbol/pair")
        if key in index:
            raise ValueError("Duplicate sensitivity row")
        index[key] = row
    # Sensitivity is optional, but a supplied split must contain its complete
    # symbol/pair matrix. Undefined values remain null, never pooled dates.
    supplied_splits = {r.split for r in rows}
    for split in supplied_splits:
        if any((split, s, *p) not in index for s in STAGE_A_SYMBOLS for p in pairs):
            raise ValueError("Incomplete sensitivity coverage")
    output = []
    for pair in pairs:
        values = []
        for field in ("state_agreement", "transition_jaccard_3"):
            medians = [_median([_value(getattr(index[split, s, *pair], field)) for s in STAGE_A_SYMBOLS])
                       if split in supplied_splits else None for split in ("selection", "out_of_sample")]
            selection, oos = medians
            values.extend([selection, oos, oos - selection if selection is not None and oos is not None else None])
        output.append(SensitivityDiagnostic(*pair, *values))
    return tuple(output)


def select_trend(metrics: Sequence[MetricRow], sensitivity: Sequence[SensitivityRow] = ()) -> SelectionResult:
    """Consume frozen tournament rows; purely synthetic fixtures during registration.

    Five candidates each have exactly 78 ranks (13 symbols x six metrics).
    Exact ties use average ranks; undefined values receive rank 5. Metric
    wins/losses count ranks exactly 1/5 (including undefined rank-5 losses).
    Null symbol medians are excluded only from diagnostic/tie-break medians,
    never from the primary-rank denominator. p75 uses linear interpolation.
    """
    index, splits = _metric_index(metrics)
    selection, ranks = _rank_split(index, "selection")
    winner = selection[0].candidate_id  # Locked before ranking any OOS data.
    oos, status = (), "PENDING"
    if "out_of_sample" in splits:
        oos, oos_ranks = _rank_split(index, "out_of_sample")
        ranks += oos_ranks
        locked = next(row for row in oos if row.candidate_id == winner)
        status = oos_validation_status(locked.mean_primary_rank)
    passed = status in ("PASS", "WEAK_PASS")
    return SelectionResult(winner, selection, status, oos, _sensitivity(sensitivity, splits),
                           ranks, winner if passed else None, passed)


def selection_report_json(result: SelectionResult) -> str:
    report = dict(
        protocol_id=PROTOCOL_ID, eligible_candidate_ids=list(ELIGIBLE_IDS),
        excluded_sensitivity_candidate_ids=list(EXCLUDED_IDS),
        primary_metrics=[m for m, _ in METRIC_DIRECTIONS], metric_directions=dict(METRIC_DIRECTIONS),
        universe=list(STAGE_A_SYMBOLS),
        splits={s.name: dict(start=s.start.isoformat(), end=s.end.isoformat()) for s in SPLITS},
        ranking_rules=dict(ties="average ranks for exact ties", undefined_rank=5,
                           ranks_per_candidate_per_split=78, p75_interpolation="linear",
                           metric_wins="rank == 1", metric_losses="rank == 5",
                           undefined_tie_break_medians="worst direction",
                           tie_break_order=["p75_primary_rank ascending", "false_reversal_rate_20 symbol median ascending",
                                            "directional_consistency_60 symbol median descending",
                                            "mae_60_median symbol median descending", "candidate_id lexical"]),
        oos_rules=dict(PASS="mean_primary_rank <= 2.5", WEAK_PASS="2.5 < mean_primary_rank <= 3.0",
                       FAIL="mean_primary_rank > 3.0; no production detector and no replacement winner"),
        sensitivity_definition="Diagnostic only; transition_jaccard_3 is +/-3 observed-bar transition timing overlap",
        **asdict(result),
    )
    return json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"


def selection_ranking_csv(result: SelectionResult) -> str:
    """UTF-8-ready deterministic content for trend_selection_ranking.csv."""
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=list(CandidateRanking.__dataclass_fields__), lineterminator="\n")
    writer.writeheader()
    for row in (*result.selection_rankings, *result.oos_rankings):
        writer.writerow(asdict(row))
    return handle.getvalue()
