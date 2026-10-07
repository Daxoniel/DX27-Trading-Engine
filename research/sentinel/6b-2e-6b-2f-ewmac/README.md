# Frozen EWMAC research archive — 6B-2E / 6B-2F

Status: **RESEARCH COMPLETE; NOT APPROVED FOR PRODUCTION**.

`ewmac_64_256` was legally selected under the frozen Stage-A protocol, with
`STAGE_A_WEAK_PASS`. Its subsequent frozen robustness validation returned
`ROBUSTNESS_FAIL`. Preserve both conclusions; do not reinterpret the winner as
an effective market-state, change-detection, or forecasting model.

## Run identity and scope

- Execution date: 2026-10-07; adjusted daily Yahoo data, 13 ETFs:
  SPY, QQQ, IWM, XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, TLT, GLD.
- Research period: 2005-01-01 through 2026-09-30; selection: 2005–2019;
  OOS: 2020–2026-09-30. Earlier observations supply warmup only.
- Stage-A runner revision: `8cc8a056950f34580631691bbd4f259153bdfe4e`.
- Robustness protocol/runner revision: `8e973e42c995d283231bf46882be1495aff61edd`.
- Canonical dataset: 77,188 rows; SHA256
  `9136494cf783f5892045e0fc52ad85166a4ede0c9b56107157a992c743cf75af`.
- Source normalization: 113 floating-boundary corrections at the frozen
  tolerance of 1e-12, documented in the data manifest.

## Decision evidence

| Measure | Frozen result |
| --- | --- |
| Winner selection mean / median / p75 rank | 2.506410 / 2 / 4 |
| Winner OOS mean rank | 2.621795 |
| Full-period DC60 | 116 / 233 = 0.497854 |
| Full-period DC60 after +3 observed-bar delay | 111 / 233 = 0.476395 |
| Delay deterioration | 0.021459; did not trigger FAIL |
| ETFs below full-period DC60 0.40 floor | SPY 0.375; XLF 0.363636; XLI 0.375; GLD 0.388889 |
| ETFs at or above DC60 0.45 | 9 / 13 |
| Final robustness decision | FAIL: more than three ETFs below 0.40 |

DC60 is the research protocol's directional-consistency metric, not a
calibrated probability of a future move or a trading success rate. Relative
ranking within this candidate set does not establish absolute utility.

Regime stress statistics pool eligible events across symbols; the minimum for
major-regime classification is 20 complete 60-observed-bar events. Forward
windows are clipped to their split/regime boundaries. Individual-symbol and
delay decision gates use the full period. Symbol medians are also reported;
they must not be substituted for pooled statistics after observing results.
The full transition audit has 235 events, of which 233 have full-period DC60
outcomes. Shorter regimes have limited evidence, not automatic validation.

Two offline robustness runs produced byte-identical artifacts. Original
Stage-A artifacts were unchanged. The 32/128 neighbour had approximately
0.877 full-period median state agreement but only 0.0345 transition Jaccard:
state agreement does not establish stable change timing.

## Retained evidence and reproducibility limits

`stage-a/` preserves the original selection lock, data manifest, rankings,
reports, summaries, metrics, sensitivity results, and original hash manifest.
`robustness/` preserves every original robustness artifact, including the
pre-registered protocol, transition audit, regime/symbol/delay tables, reports,
and original hash manifest. These files are copied without modification.
`archive_manifest.json` verifies the archived subset independently.

The large adjusted-daily dataset and per-bar candidate-state CSV are not
committed. Their exact hashes are retained in both the original Stage-A
manifest and `archive_manifest.json`; the execution workspace currently retains
these files under `/workspace/work/task-6b-2e-yahoo-20261007`. Robustness source
outputs are under `/workspace/work/task-6b-2f-robustness-20261007`.
Workspace paths are provenance, not durable repository dependencies. The
repository archive is sufficient to inspect the decision, but a full rerun
requires the exact externally retained dataset and state artifact. A new Yahoo
download may differ through vendor revisions and is not a byte-identical rerun.

## Consequence

Keep EWMAC as a reproducible research baseline; do not wire it into production
Sentinel detection. Do not tune it against this failed evaluation and reuse the
same OOS period as fresh confirmation. Next work is **6B-2G — Multi-Sensor
Contracts & Validation Protocol**, defined in the
[architecture](../../../docs/architecture/sentinel-multi-sensor-design.md) and
[roadmap](../../../TODO.md).
