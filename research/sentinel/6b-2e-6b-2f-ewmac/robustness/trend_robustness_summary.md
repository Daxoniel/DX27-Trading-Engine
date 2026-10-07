# Task 6B-2F frozen-winner robustness

Winner: ewmac_64_256. Stage-A remains STAGE_A_WEAK_PASS.
Execution commit: 8e973e42c995d283231bf46882be1495aff61edd
Dataset SHA256: 9136494cf783f5892045e0fc52ad85166a4ede0c9b56107157a992c743cf75af
Protocol SHA256: 7bcdbba2ac18479e4a349d73a7c462da24d0785360a5766c186aa2bec8696fb7

## Fixed evaluation semantics

Rates pooled from integer eligible/event counts; MFE/MAE pooled event medians; duration pooled directional-run median. Also report unweighted symbol medians.
At least 20 transitions with complete 60 observed-bar forward windows within that regime, pooled across the fixed 13 ETFs.
Existing evaluate_metrics semantics, clipped at the relevant scope end; no crossing regime/split ends. Audit includes full-period and regime-clipped outcomes.

## Regimes

| label | transition_count | valid_transitions | false_reversal_rate_10 | false_reversal_rate_20 | directional_consistency_20 | directional_consistency_60 | mfe_60_median | mae_60_median | median_state_duration |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pre_gfc_expansion | 19 | 15 | 0.000000 | 0.058824 | 0.647059 | 0.466667 | 0.053313 | -0.025632 | 227.500000 |
| global_financial_crisis | 16 | 15 | 0.000000 | 0.000000 | 0.625000 | 0.533333 | 0.081810 | -0.071982 | 123 |
| post_gfc_bull_qe | 60 | 57 | 0.083333 | 0.183333 | 0.550000 | 0.596491 | 0.053584 | -0.060078 | 115 |
| late_cycle_pre_covid | 56 | 55 | 0.053571 | 0.142857 | 0.446429 | 0.400000 | 0.036773 | -0.042030 | 97 |
| covid_shock_recovery | 16 | 15 | 0.062500 | 0.125000 | 0.250000 | 0.533333 | 0.062419 | -0.081598 | 94 |
| post_covid_risk_on | 11 | 6 | 0.100000 | 0.222222 | 0.444444 | 0.500000 | 0.033471 | -0.045379 | 117.500000 |
| inflation_rate_shock | 16 | 10 | 0.000000 | 0.000000 | 0.600000 | 0.500000 | 0.075394 | -0.051257 | 95 |
| current_post_2022 | 41 | 39 | 0.051282 | 0.102564 | 0.564103 | 0.512821 | 0.047692 | -0.045230 | 92.000000 |

## Asset groups (full period)

| label | transition_count | valid_transitions | false_reversal_rate_10 | false_reversal_rate_20 | directional_consistency_20 | directional_consistency_60 | mfe_60_median | mae_60_median | median_state_duration |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| broad_equity | 48 | 48 | 0.041667 | 0.125000 | 0.479167 | 0.458333 | 0.060101 | -0.066739 | 221 |
| equity_sectors | 136 | 134 | 0.059701 | 0.126866 | 0.559701 | 0.522388 | 0.054795 | -0.060975 | 172.000000 |
| rates | 33 | 33 | 0.060606 | 0.181818 | 0.484848 | 0.515152 | 0.033943 | -0.032253 | 96.000000 |
| gold | 18 | 18 | 0.055556 | 0.111111 | 0.388889 | 0.388889 | 0.033980 | -0.046709 | 130 |

## Symbols (full period)

| label | transition_count | valid_transitions | false_reversal_rate_10 | false_reversal_rate_20 | directional_consistency_20 | directional_consistency_60 | mfe_60_median | mae_60_median | median_state_duration |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SPY | 16 | 16 | 0.062500 | 0.187500 | 0.375000 | 0.375000 | 0.052338 | -0.083703 | 221 |
| QQQ | 12 | 12 | 0.000000 | 0.000000 | 0.583333 | 0.500000 | 0.073420 | -0.048445 | 261 |
| IWM | 20 | 20 | 0.050000 | 0.150000 | 0.500000 | 0.500000 | 0.065647 | -0.062811 | 106 |
| XLK | 16 | 16 | 0.125000 | 0.187500 | 0.687500 | 0.500000 | 0.056607 | -0.065290 | 270 |
| XLF | 22 | 22 | 0.045455 | 0.136364 | 0.454545 | 0.363636 | 0.053141 | -0.080964 | 155 |
| XLE | 18 | 18 | 0.111111 | 0.111111 | 0.666667 | 0.666667 | 0.073544 | -0.037966 | 226 |
| XLV | 18 | 18 | 0.055556 | 0.055556 | 0.611111 | 0.555556 | 0.052900 | -0.031165 | 151 |
| XLI | 16 | 16 | 0.000000 | 0.000000 | 0.625000 | 0.375000 | 0.057238 | -0.068804 | 138 |
| XLP | 14 | 14 | 0.071429 | 0.142857 | 0.428571 | 0.571429 | 0.039038 | -0.046565 | 180 |
| XLY | 17 | 16 | 0.062500 | 0.250000 | 0.562500 | 0.625000 | 0.064380 | -0.034076 | 182.000000 |
| XLU | 15 | 14 | 0.000000 | 0.142857 | 0.428571 | 0.571429 | 0.031899 | -0.055779 | 158.000000 |
| TLT | 33 | 33 | 0.060606 | 0.181818 | 0.484848 | 0.515152 | 0.033943 | -0.032253 | 96.000000 |
| GLD | 18 | 18 | 0.055556 | 0.111111 | 0.388889 | 0.388889 | 0.033980 | -0.046709 | 130 |

## Timing perturbation (full period)

| label | transition_count | valid_transitions | false_reversal_rate_10 | false_reversal_rate_20 | directional_consistency_20 | directional_consistency_60 | mfe_60_median | mae_60_median | median_state_duration | state_agreement | transition_jaccard_3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| delay_0 | 235 | 233 | 0.055794 | 0.133047 | 0.519313 | 0.497854 | 0.052699 | -0.050952 | 142.500000 | 1.000000 | 1.000000 |
| delay_1 | 234 | 232 | 0.055794 | 0.133047 | 0.545064 | 0.517241 | 0.049551 | -0.052868 | 143 | 0.996685 | 0.995745 |
| delay_2 | 234 | 232 | 0.055794 | 0.133047 | 0.489270 | 0.487069 | 0.051798 | -0.055139 | 143 | 0.993383 | 0.995745 |
| delay_3 | 235 | 233 | 0.055556 | 0.132479 | 0.500000 | 0.476395 | 0.047948 | -0.059161 | 143 | 0.990082 | 0.991525 |

## Cross-symbol dispersion

| metric | median | p25 | p75 | best_symbol | worst_symbol |
| --- | --- | --- | --- | --- | --- |
| false_reversal_rate_10 | 0.055556 | 0.045455 | 0.062500 | QQQ | XLK |
| false_reversal_rate_20 | 0.142857 | 0.111111 | 0.181818 | QQQ | XLY |
| directional_consistency_20 | 0.500000 | 0.428571 | 0.611111 | XLK | SPY |
| directional_consistency_60 | 0.500000 | 0.388889 | 0.571429 | XLE | XLF |
| mfe_60_median | 0.053141 | 0.039038 | 0.064380 | XLE | XLU |
| mae_60_median | -0.048445 | -0.065290 | -0.037966 | XLV | SPY |
| transitions | 17.000000 | 16.000000 | 18.000000 | TLT | QQQ |
| median_state_duration | 158.000000 | 138.000000 | 221.000000 | XLK | TLT |
| false_reversal_10_count | 1.000000 | 1.000000 | 1.000000 | QQQ | XLK |
| false_reversal_20_count | 2.000000 | 2.000000 | 3.000000 | QQQ | TLT |

## Transition audit

{
  "by_regime": {
    "covid_shock_recovery": 16,
    "current_post_2022": 41,
    "global_financial_crisis": 16,
    "inflation_rate_shock": 16,
    "late_cycle_pre_covid": 56,
    "post_covid_risk_on": 11,
    "post_gfc_bull_qe": 60,
    "pre_gfc_expansion": 19
  },
  "by_symbol": {
    "GLD": 18,
    "IWM": 20,
    "QQQ": 12,
    "SPY": 16,
    "TLT": 33,
    "XLE": 18,
    "XLF": 22,
    "XLI": 16,
    "XLK": 16,
    "XLP": 14,
    "XLU": 15,
    "XLV": 18,
    "XLY": 17
  },
  "full_period_eligible_60": 233,
  "regime_clipped_eligible_60": 212,
  "total": 235
}


## Neighbour diagnostic: unweighted symbol medians

| scope | neighbour | state_agreement | transition_jaccard_3 | median_absolute_transition_timing_difference | disagreement_rate |
| --- | --- | --- | --- | --- | --- |
| full | ewmac_32_128 | 0.876782 | 0.034483 | 1.000000 | 0.123218 |
| full | ewmac_16_64 | 0.761609 | 0.016949 | 2 | 0.238391 |
| selection | ewmac_32_128 | 0.879470 | 0.028571 | 1.000000 | 0.120530 |
| selection | ewmac_16_64 | 0.760795 | 0.015873 | 1.500000 | 0.239205 |
| out_of_sample | ewmac_32_128 | 0.875516 | 0.043478 | 1 | 0.124484 |
| out_of_sample | ewmac_16_64 | 0.735103 | 0.000000 | 2 | 0.264897 |
| pre_gfc_expansion | ewmac_32_128 | 0.889368 | 0.000000 | 2.500000 | 0.110632 |
| pre_gfc_expansion | ewmac_16_64 | 0.761494 | 0.000000 | 2.000000 | 0.238506 |
| global_financial_crisis | ewmac_32_128 | 0.870787 | 0.000000 | 3 | 0.129213 |
| global_financial_crisis | ewmac_16_64 | 0.758427 | 0.000000 | 2 | 0.241573 |
| post_gfc_bull_qe | ewmac_32_128 | 0.870122 | 0.000000 | 1.000000 | 0.129878 |
| post_gfc_bull_qe | ewmac_16_64 | 0.762376 | 0.000000 | 1.500000 | 0.237624 |
| late_cycle_pre_covid | ewmac_32_128 | 0.891650 | 0.000000 | 1 | 0.108350 |
| late_cycle_pre_covid | ewmac_16_64 | 0.761431 | 0.000000 | 1.000000 | 0.238569 |
| covid_shock_recovery | ewmac_32_128 | 0.881423 | 0.000000 | 3 | 0.118577 |
| covid_shock_recovery | ewmac_16_64 | 0.833992 | 0.000000 | undefined | 0.166008 |
| post_covid_risk_on | ewmac_32_128 | 1.000000 | 0.000000 | 2.500000 | 0.000000 |
| post_covid_risk_on | ewmac_16_64 | 0.888889 | 0.000000 | 1.750000 | 0.111111 |
| inflation_rate_shock | ewmac_32_128 | 0.788845 | 0.000000 | 0.000000 | 0.211155 |
| inflation_rate_shock | ewmac_16_64 | 0.613546 | 0.000000 | undefined | 0.386454 |
| current_post_2022 | ewmac_32_128 | 0.880724 | 0.000000 | 1 | 0.119276 |
| current_post_2022 | ewmac_16_64 | 0.759318 | 0.000000 | 2.500000 | 0.240682 |

Matching timing difference is conditional on +/-3-bar matches; unmatched transitions are not assigned a fabricated lag.

## Decision

{
  "delay3_directional_60_deterioration": 0.02145922746781116,
  "descriptive_only_regimes": [
    "pre_gfc_expansion",
    "global_financial_crisis",
    "covid_shock_recovery",
    "post_covid_risk_on",
    "inflation_rate_shock"
  ],
  "fail_conditions": [
    "More than three ETFs have directional_consistency_60 < 0.40"
  ],
  "major_regimes": [
    "post_gfc_bull_qe",
    "late_cycle_pre_covid",
    "current_post_2022"
  ],
  "symbols_at_least_045": [
    "QQQ",
    "IWM",
    "XLK",
    "XLE",
    "XLV",
    "XLP",
    "XLY",
    "XLU",
    "TLT"
  ],
  "symbols_below_040": [
    "SPY",
    "XLF",
    "XLI",
    "GLD"
  ],
  "undefined_conditions": [],
  "verdict": "ROBUSTNESS_FAIL"
}

ROBUSTNESS_FAIL
frozen_winner = ewmac_64_256
winner_reselected = false
stage_a_result_changed = false
production_trend_detector_created = false
