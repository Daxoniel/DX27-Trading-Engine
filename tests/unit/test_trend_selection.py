"""Synthetic-only protocol fixtures; never read saved real-data artifacts."""
import ast
import csv
import io
import json
import random
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from dx27.intelligence.sentinel.research import trend_selection as s
from dx27.intelligence.sentinel.research.trend_metrics import MetricRow, SensitivityRow
from dx27.intelligence.sentinel.research.trend_models import CANDIDATES


def fixtures(selection_order=None, oos_order=None, *, include_oos=True):
    selection_order = selection_order or s.ELIGIBLE_IDS
    oos_order = oos_order or selection_order
    rows = []
    for split, order in [("selection", selection_order), *(([("out_of_sample", oos_order)]) if include_oos else [])]:
        for symbol in s.STAGE_A_SYMBOLS:
            for candidate in CANDIDATES:
                rank = order.index(candidate.candidate_id) + 1 if candidate.candidate_id in order else 0
                values = {m: rank / 10 if direction == "lower" else 1 - rank / 10
                          for m, direction in s.METRIC_DIRECTIONS}
                values["mae_60_median"] = -rank / 10
                values.update(transition_rate_per_252=rank * 100, persistence_median=rank * 7)
                rows.append(MetricRow(split, symbol, candidate.candidate_id, candidate.family, values))
    return rows


def change(rows, split, candidate, values):
    return [replace(r, values=dict(r.values, **values)) if r.split == split and r.candidate_id == candidate else r
            for r in rows]


def test_eligibility_derived_from_candidates_and_sensitivity_never_wins():
    assert s.ELIGIBLE_IDS == tuple(c.candidate_id for c in CANDIDATES if not c.sensitivity_only)
    assert set(s.ELIGIBLE_IDS) == {"ewmac_16_64", "ewmac_32_128", "ewmac_64_256", "tsmom_252", "lean_ema_cross_12_26"}
    result = s.select_trend(fixtures())
    assert result.selection_winner == s.ELIGIBLE_IDS[0]
    assert result.final_winner == result.selection_winner
    assert not set(s.EXCLUDED_IDS) & {r.candidate_id for r in result.selection_rankings}
    assert result.production_trend_detector_created is False
    assert result.selection_rankings[0].mean_primary_rank == 1
    assert result.selection_rankings[0].number_of_metric_wins == 78
    assert result.selection_rankings[-1].number_of_metric_losses == 78


@pytest.mark.parametrize("metric,direction", s.METRIC_DIRECTIONS)
def test_each_primary_metric_direction(metric, direction):
    result = s.select_trend(fixtures())
    observations = [r for r in result.primary_ranks if r.split == "selection" and r.symbol == "SPY" and r.metric == metric]
    assert [r.rank for r in observations] == [1., 2., 3., 4., 5.]
    assert observations[0].value < observations[-1].value if direction == "lower" else observations[0].value > observations[-1].value


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_missing_worst_rank_without_dropping_observations(missing):
    candidate = s.ELIGIBLE_IDS[0]
    rows = change(fixtures(), "selection", candidate, {m: missing for m, _ in s.METRIC_DIRECTIONS})
    result = s.select_trend(rows)
    observation = [r for r in result.primary_ranks if r.split == "selection" and r.candidate_id == candidate]
    assert len(observation) == 78
    assert all(r.rank == 5 and r.value is None for r in observation)
    ranking = next(r for r in result.selection_rankings if r.candidate_id == candidate)
    assert ranking.mean_primary_rank == 5 and ranking.number_of_metric_losses == 78
    assert result.selection_winner != candidate
    s.selection_report_json(result)


def test_missing_metric_key_gets_worst_rank():
    rows = fixtures()
    index = next(i for i, r in enumerate(rows) if r.candidate_id in s.ELIGIBLE_IDS)
    row = rows[index]
    values = dict(row.values)
    values.pop("false_reversal_rate_10")
    rows[index] = replace(row, values=values)
    result = s.select_trend(rows)
    observation = next(r for r in result.primary_ranks if (r.split, r.symbol, r.candidate_id, r.metric) ==
                       (row.split, row.symbol, row.candidate_id, "false_reversal_rate_10"))
    assert observation.rank == 5 and observation.value is None


def test_exact_average_ties_and_lexical_final_tie_break():
    rows = [replace(r, values={m: .1 for m, _ in s.METRIC_DIRECTIONS}) for r in fixtures()]
    result = s.select_trend(rows)
    assert all(r.rank == 3 for r in result.primary_ranks)
    assert result.selection_winner == min(s.ELIGIBLE_IDS)
    assert result.oos_validation_status == "WEAK_PASS"
    assert all(r.number_of_metric_wins == r.number_of_metric_losses == 0 for r in result.selection_rankings)


@pytest.mark.parametrize("field,better", [("p75_primary_rank", 2.0),
    ("false_reversal_rate_20_symbol_median", .1),
    ("directional_consistency_60_symbol_median", .9), ("mae_60_symbol_median", -.01),
    ("candidate_id", "a")])
def test_all_tie_break_levels_and_priority(field, better):
    base = s.CandidateRanking("selection", "z", 2., 2., 3., 0, 0, .5, .5, -.5, 99., 99.)
    preferred = replace(base, **{field: better})
    # Later tie-breaks deliberately favor the other candidate.
    if field != "candidate_id":
        preferred = replace(preferred, candidate_id="zz")
    assert sorted([base, preferred], key=s._tie_key)[0] == preferred
    assert sorted([preferred, base], key=s._tie_key)[0] == preferred


@pytest.mark.parametrize("field", ["false_reversal_rate_20_symbol_median",
                                   "directional_consistency_60_symbol_median", "mae_60_symbol_median"])
def test_undefined_tie_break_medians_sort_worst(field):
    base = s.CandidateRanking("selection", "z", 2., 2., 3., 0, 0, .5, .5, -.5, 99., 99.)
    absent = replace(base, candidate_id="a", **{field: None})
    assert sorted([absent, base], key=s._tie_key)[0] == base


def test_primary_mean_precedes_tie_breaks():
    base = s.CandidateRanking("selection", "a", 2., 2., 1., 0, 0, .1, .9, -.01, 99., 99.)
    better_mean = replace(base, candidate_id="z", mean_primary_rank=1.9, p75_primary_rank=5.)
    assert sorted([base, better_mean], key=s._tie_key)[0] == better_mean


@pytest.mark.parametrize("rank,status", [(1., "PASS"), (2.5, "PASS"), (2.500001, "WEAK_PASS"),
                                         (3., "WEAK_PASS"), (3.000001, "FAIL"), (5., "FAIL")])
def test_oos_exact_boundaries(rank, status):
    assert s.oos_validation_status(rank) == status


@pytest.mark.parametrize("position,status", [(0, "PASS"), (1, "PASS"), (2, "WEAK_PASS"), (3, "FAIL"), (4, "FAIL")])
def test_oos_cannot_replace_locked_winner(position, status):
    selection = list(s.ELIGIBLE_IDS)
    order = selection[1:]
    order.insert(position, selection[0])
    result = s.select_trend(fixtures(selection, order))
    assert result.selection_winner == selection[0]
    assert result.oos_validation_status == status
    assert result.winner_selected == (status != "FAIL")
    assert result.final_winner == (selection[0] if status != "FAIL" else None)
    if position:
        assert result.oos_rankings[0].candidate_id != result.selection_winner


def test_oos_changes_cannot_influence_selection():
    a = s.select_trend(fixtures())
    b = s.select_trend(fixtures(oos_order=tuple(reversed(s.ELIGIBLE_IDS))))
    assert a.selection_winner == b.selection_winner
    assert a.selection_rankings == b.selection_rankings
    assert tuple(r for r in a.primary_ranks if r.split == "selection") == tuple(r for r in b.primary_ranks if r.split == "selection")
    assert b.final_winner is None and b.winner_selected is False


def test_selection_only_remains_provisional():
    result = s.select_trend(fixtures(include_oos=False))
    assert result.selection_winner == s.ELIGIBLE_IDS[0]
    assert result.oos_validation_status == "PENDING"
    assert not result.oos_rankings and result.final_winner is None and not result.winner_selected


def sensitivity_fixtures():
    rows = []
    from itertools import combinations
    for split, offset in [("selection", 0.), ("out_of_sample", .1)]:
        for family in ("ewmac", "tsmom"):
            for a, b in combinations(sorted(c.candidate_id for c in CANDIDATES if c.family == family), 2):
                for i, symbol in enumerate(s.STAGE_A_SYMBOLS):
                    rows.append(SensitivityRow(split, symbol, family, a, b, 100, i / 20 + offset,
                                               10, 10, 5, i / 30 + offset))
    return rows


def test_sensitivity_medians_delta_and_no_score_effect():
    without = s.select_trend(fixtures())
    result = s.select_trend(fixtures(), sensitivity_fixtures())
    assert len(result.sensitivity_diagnostics) == 12
    for r in result.sensitivity_diagnostics:
        assert r.selection_state_agreement_symbol_median == pytest.approx(.3)
        assert r.oos_state_agreement_symbol_median == pytest.approx(.4)
        assert r.state_agreement_delta_oos_minus_selection == pytest.approx(.1)
        assert r.selection_transition_jaccard_3_symbol_median == pytest.approx(.2)
        assert r.transition_jaccard_3_delta_oos_minus_selection == pytest.approx(.1)
    assert result.selection_rankings == without.selection_rankings
    assert result.selection_winner == without.selection_winner


def test_sensitivity_nulls_not_pooled():
    rows = [replace(r, state_agreement=None) for r in sensitivity_fixtures()]
    result = s.select_trend(fixtures(), rows)
    assert all(r.selection_state_agreement_symbol_median is None and r.state_agreement_delta_oos_minus_selection is None
               for r in result.sensitivity_diagnostics)


def test_diagnostics_do_not_affect_winner():
    rows = [replace(r, values=dict(r.values, transition_rate_per_252=99999., persistence_median=99999.)) for r in fixtures()]
    a, b = s.select_trend(fixtures()), s.select_trend(rows)
    assert a.selection_winner == b.selection_winner
    assert a.primary_ranks == b.primary_ranks
    assert all(r.transition_rate_per_252_symbol_median == 99999. for r in b.selection_rankings)


def test_order_invariant_immutable_results_and_serialization():
    rows, sensitivity = fixtures(), sensitivity_fixtures()
    result = s.select_trend(rows, sensitivity)
    random.Random(42).shuffle(rows)
    random.Random(43).shuffle(sensitivity)
    repeated = s.select_trend(rows, sensitivity)
    assert repeated == result
    assert s.selection_report_json(result) == s.selection_report_json(repeated)
    assert s.selection_ranking_csv(result) == s.selection_ranking_csv(repeated)
    with pytest.raises(FrozenInstanceError):
        result.selection_winner = "tsmom_21"
    with pytest.raises(FrozenInstanceError):
        result.selection_rankings[0].mean_primary_rank = 0
    report = json.loads(s.selection_report_json(result))
    assert report["protocol_id"] == "dx27.trend.stage_a.selection.v0.1"
    assert report["primary_metrics"] == [m for m, _ in s.METRIC_DIRECTIONS]
    assert report["metric_directions"] == dict(s.METRIC_DIRECTIONS)
    assert report["production_trend_detector_created"] is False
    serialized = list(csv.DictReader(io.StringIO(s.selection_ranking_csv(result))))
    assert len(serialized) == 10
    assert {r["split"] for r in serialized} == {"selection", "out_of_sample"}
    assert "timestamp" not in report


@pytest.mark.parametrize("case", ["missing", "duplicate", "symbol", "split", "family", "infinity"])
def test_invalid_inputs_fail_closed(case):
    rows = fixtures()
    i = next(i for i, r in enumerate(rows) if r.candidate_id == s.ELIGIBLE_IDS[0])
    if case == "missing":
        rows.pop(i)
    elif case == "duplicate":
        rows.append(rows[i])
    elif case == "infinity":
        rows[i] = replace(rows[i], values={"false_reversal_rate_10": float("inf")})
    else:
        rows[i] = replace(rows[i], **{case: "invalid"})
    with pytest.raises(ValueError):
        s.select_trend(rows)


def test_incomplete_sensitivity_rejected():
    with pytest.raises(ValueError, match="Incomplete"):
        s.select_trend(fixtures(), sensitivity_fixtures()[:-1])


def test_no_forbidden_dependency_or_file_io():
    source = Path(s.__file__).read_text()
    tree = ast.parse(source)
    forbidden = {"yfinance", "yahoo", "execution", "portfolio", "risk", "approval", "bots", "runners"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(set(n.split(".")) & forbidden for n in names)
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open" for n in ast.walk(tree))


def test_integrated_mean_tie_uses_p75():
    ids = list(s.ELIGIBLE_IDS)
    first, second = [1, 3, 2, 4, 5], [4, 2, 5, 3, 1]
    rows = fixtures(include_oos=False)
    changed = []
    for row in rows:
        if row.candidate_id not in ids:
            changed.append(row)
            continue
        index = ids.index(row.candidate_id)
        values = dict(row.values)
        for i, (metric, direction) in enumerate(s.METRIC_DIRECTIONS):
            rank = (first if i < 3 else second)[index]
            values[metric] = rank / 10 if direction == "lower" else -rank / 10
        changed.append(replace(row, values=values))
    result = s.select_trend(changed)
    a, b = (next(r for r in result.selection_rankings if r.candidate_id == c) for c in ids[:2])
    assert a.mean_primary_rank == b.mean_primary_rank == 2.5
    assert a.p75_primary_rank == 4 and b.p75_primary_rank == 3
    assert result.selection_winner == ids[1]
