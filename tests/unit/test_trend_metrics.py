from datetime import date, timedelta

import pytest

from dx27.intelligence.sentinel.research.trend_metrics import (
    DateSplit, directional_transitions, evaluate_metrics, evaluate_sensitivity,
    match_transitions, persistence_lengths, state_agreement,
)
from dx27.intelligence.sentinel.research.trend_models import CANDIDATES, TrendObservation, TrendState


B, S, Z = TrendState.BULLISH, TrendState.BEARISH, TrendState.NEUTRAL
SPLIT = DateSplit("selection", date(2019, 1, 1), date(2019, 12, 31))


def observations(states, candidate=CANDIDATES[1], days=None):
    days = days or [date(2019, 1, 1) + timedelta(days=3 * i) for i in range(len(states))]
    return tuple(TrendObservation("SPY", day, candidate.candidate_id, candidate.family,
                                  state, None, None, None, None, state is not None,
                                  candidate.source_classification, candidate.sensitivity_only)
                 for day, state in zip(days, states))


def metrics(states, closes=None, split=SPLIT, days=None):
    return evaluate_metrics(observations(states, days=days), closes or [100] * len(states), split).values


def test_primary_transition_excludes_none_and_neutral():
    states = [None, B, Z, S, None, B, S, B]
    assert directional_transitions(states) == (6, 7)


def test_persistence_breaks_on_neutral_none_opposite_and_end():
    states = [B, B, Z, B, None, S, S, S, B]
    assert persistence_lengths(states) == (2, 1, 3, 1)
    result = metrics(states)
    assert result["persistence_count"] == 4
    assert result["persistence_mean"] == 1.75
    assert result["persistence_median"] == 1.5
    assert result["persistence_p25"] == 1
    assert result["persistence_p75"] == 2.25


def test_transition_rate_counts_neutral_evaluated_but_not_none():
    result = metrics([None, B, S, Z, B, B, S])
    assert result["evaluated_days"] == 6
    assert result["transitions"] == 2
    assert result["transition_rate_per_252"] == 2 / 6 * 252


@pytest.mark.parametrize("states", [[None] * 5, [Z] * 5])
def test_no_eligible_persistence_is_none_not_zero(states):
    result = metrics(states)
    for key in ("persistence_count", "persistence_mean", "persistence_median", "persistence_p25", "persistence_p75"):
        assert result[key] is None
    assert result["transitions"] == 0
    assert result["transition_rate_per_252"] == (None if states[0] is None else 0)


@pytest.mark.parametrize("horizon", [5, 10, 20])
def test_false_reversal_returns_to_old_state_through_neutral(horizon):
    # One primary S->B transition; Z->S is not a second primary transition.
    states = [S, B] + [Z] * (horizon - 1) + [S]
    result = metrics(states)
    assert result[f"eligible_false_reversal_{horizon}"] == 1
    assert result[f"false_reversal_rate_{horizon}"] == 1


@pytest.mark.parametrize("horizon", [5, 10, 20])
def test_false_reversal_available_observations_exclude_none(horizon):
    states = [S, B, None] + [Z] * (horizon - 1) + [S]
    result = metrics(states)
    assert result[f"eligible_false_reversal_{horizon}"] == 1
    assert result[f"false_reversal_rate_{horizon}"] == 1
    result = metrics([S, B, None] + [Z] * (horizon - 1))
    assert result[f"eligible_false_reversal_{horizon}"] == 0
    assert result[f"false_reversal_rate_{horizon}"] is None


def test_false_reversal_tail_excluded_from_denominator():
    # Transition at 1 has 5 observations; transition at 6 is ineligible.
    result = metrics([S, B, B, B, B, B, S])
    assert result["transitions"] == 2
    assert result["eligible_false_reversal_5"] == 1
    assert result["false_reversal_rate_5"] == 1
    assert result["eligible_false_reversal_10"] == 0
    assert result["false_reversal_rate_10"] is None


def test_false_reversal_eligible_nonreversal_is_zero():
    result = metrics([S] + [B] * 22)
    for horizon in (5, 10, 20):
        assert result[f"eligible_false_reversal_{horizon}"] == 1
        assert result[f"false_reversal_rate_{horizon}"] == 0


@pytest.mark.parametrize("direction", [B, S])
@pytest.mark.parametrize("horizon", [5, 10, 20, 60])
def test_directional_consistency_exact_observed_bar_horizon(direction, horizon):
    states = [TrendState(-direction)] + [direction] * (horizon + 1)
    closes = [100, 100] + [100 + int(direction) * i for i in range(1, horizon + 1)]
    result = metrics(states, closes)
    assert result[f"eligible_directional_{horizon}"] == 1
    assert result[f"directional_consistency_{horizon}"] == 1
    result = metrics(states, [200 - price for price in closes])
    assert result[f"directional_consistency_{horizon}"] == 0


@pytest.mark.parametrize("horizon", [5, 10, 20, 60])
def test_zero_forward_return_not_consistent_and_tail_ineligible(horizon):
    states = [S] + [B] * (horizon + 1)
    result = metrics(states)
    assert result[f"eligible_directional_{horizon}"] == 1
    assert result[f"directional_consistency_{horizon}"] == 0
    tail = metrics(states[:-1])
    assert tail[f"eligible_directional_{horizon}"] == 0
    assert tail[f"directional_consistency_{horizon}"] is None


@pytest.mark.parametrize("horizon", [20, 60])
@pytest.mark.parametrize("direction", [B, S])
def test_close_based_mfe_mae_direction_sign_and_no_entry_zero(horizon, direction):
    states = [TrendState(-direction)] + [direction] * (horizon + 1)
    closes = [100, 100, 120, 90] + [105] * (horizon - 2)
    result = metrics(states, closes)
    expected_mfe, expected_mae = ((0.2, -0.1) if direction == B else (0.1, -0.2))
    for stat in ("mean", "median"):
        assert result[f"mfe_{horizon}_{stat}"] == pytest.approx(expected_mfe)
        assert result[f"mae_{horizon}_{stat}"] == pytest.approx(expected_mae)
    # All future directional returns negative: MFE must remain negative.
    closes = [100, 100] + [90 if direction == B else 110] * horizon
    result = metrics(states, closes)
    assert result[f"mfe_{horizon}_mean"] == pytest.approx(-0.1)
    assert result[f"mae_{horizon}_mean"] == pytest.approx(-0.1)


def test_state_agreement_includes_neutral_excludes_unavailable():
    assert state_agreement([None, B, S, Z, B], [B, B, B, Z, None]) == (3, 2 / 3)
    assert state_agreement([None], [B]) == (0, None)
    with pytest.raises(ValueError):
        state_agreement([B], [])


def test_transition_matching_is_greedy_nearest_and_earlier_tiebreak():
    assert match_transitions([10, 3], [12, 8, 4]) == ((3, 4), (10, 8))
    assert match_transitions([10], [13, 8, 9]) == ((10, 9),)
    assert match_transitions([10], [7, 13]) == ((10, 7),)
    assert match_transitions([10], [6, 14]) == ()


def test_transition_matching_never_reuses_b_and_obeys_a_order():
    assert match_transitions([11, 10], [12]) == ((10, 12),)
    assert match_transitions([], []) == ()


def test_sensitivity_jaccard_and_same_family_only():
    states_a = [B, B, S, S, B, B, B]
    states_b = [B, B, B, S, S, S, S]
    series = {c.candidate_id: observations(states_a if c.candidate_id == "ewmac_8_32" else states_b, c)
              for c in CANDIDATES}
    rows = evaluate_sensitivity(series, SPLIT)
    assert len(rows) == 12
    row = next(r for r in rows if r.candidate_a == "ewmac_16_64" and r.candidate_b == "ewmac_8_32")
    assert row.common_evaluated_dates == 7
    assert row.state_agreement == 3 / 7
    assert (row.transitions_a, row.transitions_b, row.transition_match_count) == (1, 2, 1)
    assert row.transition_jaccard_3 == 1 / 2
    assert all(r.family in ("ewmac", "tsmom") for r in rows)
    assert all(r.candidate_a.split("_")[0] == r.candidate_b.split("_")[0] for r in rows)


def test_sensitivity_empty_denominators_return_none():
    series = {c.candidate_id: observations([None, None], c) for c in CANDIDATES}
    rows = evaluate_sensitivity(series, SPLIT)
    assert all(r.state_agreement is None and r.transition_jaccard_3 is None for r in rows)
    assert all(r.common_evaluated_dates == r.transition_match_count == 0 for r in rows)


def test_split_clips_forward_windows_and_persistence_keeps_boundary_transition():
    days = [date(2019, 12, 30), date(2019, 12, 31)] + [date(2020, 1, 1) + timedelta(days=i) for i in range(65)]
    states = [S] + [B] * 66
    selection = metrics(states, days=days)
    assert selection["transitions"] == 1
    assert selection["persistence_count"] == 2
    assert selection["eligible_false_reversal_5"] == 0
    assert selection["eligible_directional_5"] == 0
    assert selection["mfe_20_mean"] is None
    out = DateSplit("out_of_sample", date(2020, 1, 1), date(2026, 9, 30))
    result = metrics(states, split=out, days=days)
    assert result["transitions"] == 0
    assert result["persistence_count"] == 1
    assert result["persistence_mean"] == 65
    states[2] = S
    result = metrics(states, split=out, days=days)
    assert result["transitions"] == 2  # OOS first bar uses its actual prior state.


def test_metric_input_alignment_and_identity_rejected():
    with pytest.raises(ValueError):
        evaluate_metrics(observations([B]), [], SPLIT)
    with pytest.raises(ValueError):
        evaluate_metrics(observations([B]) + observations([B], CANDIDATES[0]), [100, 100], SPLIT)
