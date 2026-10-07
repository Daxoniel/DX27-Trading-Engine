# Stage-A frozen research

Protocol: `dx27.trend.stage_a.selection.v0.1`
Execution commit: `8cc8a056950f34580631691bbd4f259153bdfe4e`
Dataset SHA256: `9136494cf783f5892045e0fc52ad85166a4ede0c9b56107157a992c743cf75af`

| Candidate | Selection mean rank | Selection p75 | Selection median | OOS mean rank | Locked status |
|---|---:|---:|---:|---:|---|
| ewmac_64_256 | 2.506410 | 4.000000 | 2.000000 | 2.621795 | WEAK_PASS |
| ewmac_32_128 | 2.576923 | 3.875000 | 2.000000 | 2.685897 |  |
| ewmac_16_64 | 2.891026 | 3.000000 | 3.000000 | 3.115385 |  |
| lean_ema_cross_12_26 | 3.352564 | 4.000000 | 4.000000 | 3.198718 |  |
| tsmom_252 | 3.673077 | 5.000000 | 4.000000 | 3.378205 |  |

Locked candidate primary metrics: unweighted medians of non-null symbol-level values across the 13 ETFs.

| Metric | Selection | OOS |
|---|---:|---:|
| false_reversal_rate_10 | 0.04545454545 | 0 |
| false_reversal_rate_20 | 0.1428571429 | 0 |
| directional_consistency_20 | 0.5 | 0.5 |
| directional_consistency_60 | 0.5 | 0.5 |
| mfe_60_median | 0.05289967512 | 0.05259068115 |
| mae_60_median | -0.04253262915 | -0.05178425664 |

Sensitivity is descriptive only; no fragility threshold or winner override is defined by the frozen protocol.

| Family | Pair | Selection agreement | OOS agreement | Agreement delta | Selection transition overlap | OOS transition overlap | Overlap delta |
|---|---|---:|---:|---:|---:|---:|---:|
| ewmac | ewmac_16_64 / ewmac_32_128 | 0.8678145695 | 0.8613569322 | -0.006457637383 | 0.06382978723 | 0.06 | -0.003829787234 |
| ewmac | ewmac_16_64 / ewmac_64_256 | 0.760794702 | 0.7351032448 | -0.02569145715 | 0.01587301587 | 0 | -0.01587301587 |
| ewmac | ewmac_16_64 / ewmac_8_32 | 0.8516556291 | 0.8507374631 | -0.0009181660122 | 0.1412429379 | 0.164556962 | 0.02331402417 |
| ewmac | ewmac_32_128 / ewmac_64_256 | 0.8794701987 | 0.8755162242 | -0.003953974487 | 0.02857142857 | 0.04347826087 | 0.0149068323 |
| ewmac | ewmac_32_128 / ewmac_8_32 | 0.7449006623 | 0.7321533923 | -0.01274726992 | 0.02380952381 | 0.03614457831 | 0.0123350545 |
| ewmac | ewmac_64_256 / ewmac_8_32 | 0.6852980132 | 0.6442477876 | -0.04105022563 | 0.007092198582 | 0 | -0.007092198582 |
| tsmom | tsmom_126 / tsmom_21 | 0.6625165563 | 0.6389380531 | -0.02357850319 | 0.09154929577 | 0.08260869565 | -0.008940600122 |
| tsmom | tsmom_126 / tsmom_252 | 0.8116556291 | 0.8064896755 | -0.005165953623 | 0.06097560976 | 0.05797101449 | -0.003004595263 |
| tsmom | tsmom_126 / tsmom_63 | 0.7901986755 | 0.7752212389 | -0.01497743656 | 0.09642857143 | 0.1317365269 | 0.03530795552 |
| tsmom | tsmom_21 / tsmom_252 | 0.6452980132 | 0.6182890855 | -0.0270089277 | 0.04866180049 | 0.05524861878 | 0.006586818298 |
| tsmom | tsmom_21 / tsmom_63 | 0.721589404 | 0.7067846608 | -0.01480474321 | 0.136 | 0.1380753138 | 0.002075313808 |
| tsmom | tsmom_252 / tsmom_63 | 0.7401324503 | 0.7274336283 | -0.01269882201 | 0.05190311419 | 0.05172413793 | -0.0001789762558 |

Provisional winner: `ewmac_64_256`.
Final verdict: `STAGE_A_WEAK_PASS`.
winner_selected = true
production_trend_detector_created = false
No OOS candidate replaces the locked selection winner. No model/formula/protocol changes after acquisition.
