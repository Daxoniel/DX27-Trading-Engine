# 6B-2K-A — Experimental Forecast Attachment

Status: **USER-AUTHORIZED EXPERIMENTAL INFERENCE; NO RESEARCH PROMOTION**.
The [observation report](sentinel-observation-report.md) can optionally attach a
fixed, locally run Chronos-2 forecast. This is a separate experimental output,
not completion of the frozen 6B-2K validation gate. `production_enabled=false`,
`admission_status=BLOCKED_DATA`, the existing research thresholds and the Windows
pilot remain unchanged. `market_now.conditional_forecasts` stays empty.

## One fixed model and seven explicit targets

[Amazon's official model card](https://huggingface.co/amazon/chronos-2) identifies
Chronos-2 as a 120M-parameter model supporting joint time-series quantiles and CPU
inference, under Apache-2.0. It is used without fine-tuning, parameter search or a
model tournament. This choice limits development and deployment work; it does
not establish an advantage in ETF returns.

| Configuration | Fixed value |
| --- | --- |
| Model | `amazon/chronos-2` |
| Hugging Face revision | `29ec3766d36d6f73f0696f85560a422f50e8498c` |
| Weight file | `model.safetensors`, 477,930,472 bytes |
| Expected weight SHA256 | `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42` |
| Packages | `chronos-forecasting==2.3.2`, `transformers==4.57.1` |
| Inference | CPU, float32; no training; no cross-origin cross-learning |
| Context | 253 consecutive completed XNYS adjusted closes per usable ETF |
| Horizon | Next five XNYS sessions, not five calendar days |
| Quantiles | 0.10, 0.50 and 0.90 |

The runtime checks the downloaded weight digest before loading. A mismatch or a
model/dependency failure leaves the experimental forecast unavailable; separately
valid market observations remain readable. First installation downloads both
PyTorch dependencies and roughly 478 MB of model weights. Subsequent runs reuse
the isolated local cache. CPU memory and runtime must be measured on the target
computer; no GPU or hosted inference subscription is required by this path.

The four absolute targets are SPY, RSP, QQQ and IWM cumulative adjusted-price
returns from the origin close to the fifth future close. Three additional targets
are the cumulative relative performances RSP/SPY, QQQ/SPY and IWM/SPY over those
same endpoints. For one ETF, a target's past context is
`log(P_s) - log(P_origin)`; for a pair it is
`log(P_numerator,s / P_SPY,s) - log(P_numerator,origin / P_SPY,origin)`.
Each series ends at zero. All usable targets are submitted as one multivariate
task so related equity series can share information. VIX, credit and rates
remain observed context; they are not supplied as extra forecast targets.

The fifth-step log-level quantiles are transformed with `expm1`. They are endpoint
cumulative-return quantiles, not sums of five daily marginal quantiles. Relative
targets are forecast directly as log ratios; their intervals are not formed by
subtracting two ETF marginal intervals. Joint input processing does not enforce
arithmetic consistency between separately predicted ETF and relative medians.

The displayed 10th–90th range is a **nominal, uncalibrated 80% interval**. It is not
an established 80% coverage guarantee. No numerical probability of an increase,
buy/sell recommendation or validated risk category is inferred from three
quantiles. Quantile crossing, nonfinite output and missing required inputs produce
an unavailable target rather than a guessed forecast.

## Baseline and interpretation

Each usable target also displays a zero-drift Gaussian random-walk baseline.
It estimates sample standard deviation from that target's 252 past log increments,
scales it by `sqrt(5)`, and converts its normal 0.10/0.50/0.90 endpoint quantiles
with `expm1`. Its median return is zero. The relative baseline uses log-ratio
increments directly. This is a simple comparator with unvalidated Gaussian and
independence assumptions, not a risk bound or a separately selected model.

[The Chronos-2 paper](https://arxiv.org/abs/2510.15821) supports the model's general
multivariate architecture, not the chosen Sentinel target/window.
[A 2026 financial-return benchmark](https://arxiv.org/abs/2606.27100) studied five
individual US equities and found small, sparse advantages over random-walk
benchmarks; it does not demonstrate universal alpha or validate these ETFs.
[A related Chronos multivariate study](https://arxiv.org/abs/2605.21504) motivates
grouping related series and reports degraded accuracy when equities and rates
are mixed; its reported level-error results do not establish our five-session
return accuracy. Verification here covers official metadata and paper abstracts,
not an independent reproduction of the papers.

[TimesFM-3's official release](https://www.research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/)
is newer, but its [official weight card](https://huggingface.co/google/timesfm-3.0-pytorch)
uses a noncommercial license. Chronos-2's smaller public checkpoint and Apache-2.0
license fit this bounded integration. No comparison winner is asserted.
Stable source IDs and the distinction between literature and local engineering
choices are recorded in
[the separate reference appendix](../../research/sentinel/references/forecast_experiment_v1.json).
The frozen reference library and G/I/J protocols are not rewritten.

## Capture, issuance and evidence

Use a dedicated observation store, never the pilot journal. Forecast extraction
requires the report's latest usable capture for each feed, exact source identity,
sealed payload/binding integrity, positive finite adjusted closes and 253
consecutive calendar-aligned prices. An older successful capture cannot substitute
for a newer failed attempt. Missing ETFs abstain individually; a relative target
requires both legs. Integrity violations are hard failures, not ordinary missing
data. The 253-close requirement differs from the observation page's 21/22-close
windows and does not satisfy S/D's original-cutoff history requirements.

`as_of` is the actual report input watermark. The origin must be the latest
completed XNYS session at that watermark. Inference must finish before the next
session's close; an expired origin cannot be presented as an earlier prediction.
The run retains `issued_at`, model revision, input capture IDs/hashes, input-context
digest and a content-derived forecast identity alongside the JSON predictions.
Reusing sealed captures with `--replay-only` creates a newly issued experimental
forecast at the present watermark; it does not recreate a historical issue time.

The HTML, Markdown and `report.json` go to a new output directory. Preserve the
original JSON if subsequently comparing predictions with outcomes. A later run
is a different issuance and cannot overwrite the existing directory. This is
local application-level retention, not tamper-proof storage certification.
Raw vendor payloads, real reports, their actual predictions and screenshots stay
local. Public examples must be synthetic. The model license does not license
redistribution of Yahoo/Cboe/ICE source data.

## Local Windows run

Use a separate checkout and virtual environment from the Windows Scheduled Task.
From the observation checkout's repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e '.[forecast]'
.\.venv\Scripts\python.exe -m dx27.adapters.sentinel.observation_runner `
  --store work/forecast-observation-captures `
  --output work/forecast-observation-output-001 `
  --forecast --forecast-cache work/forecast-model-cache
```

For an existing dedicated observation store, add `--replay-only` and choose a
different, new `--output` directory. Do not point the command at the pilot store.
The first dependency/model downloads can be substantial; allow them to finish
before evaluating inference time. For a Linux CPU-only environment, install
`torch==2.8.0` from `https://download.pytorch.org/whl/cpu` before the same forecast
extra. No scheduler, email or autonomous trading is started by this command.
The verified model run used `HF_HUB_DISABLE_XET=1` to select Hugging Face's
standard HTTP download transport; set `$env:HF_HUB_DISABLE_XET = '1'` in
PowerShell if reproducing that transport. It does not disable TLS or the proxy.

## Verification and remaining claims

Software verification checks independent endpoint transforms, direct relative
inputs, calendar alignment, failure propagation, expiry, evidence retention and
observation/forecast separation. Synthetic renderer examples verify disclosure
and unavailable states. Prior observation-only ZIPs/screenshots are not acceptance
evidence for this new forecast section.

The separate diagnostic runner fixes 24 origins, spaced five sessions apart,
with nonoverlapping five-session outcome windows. It needs 373 consecutive closes
per usable ETF: 253 context closes plus 120 outcome/history sessions. Each origin
uses only its 253-close prefix; cross-origin cross-learning remains disabled.
Four complete ETF inputs produce seven targets and 168 origin-target pairs, but
only 24 nonoverlapping outcome windows; related targets are not 168 independent
samples. There is one model configuration and no model/parameter selection.

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.sentinel.forecast_diagnostic `
  --store work/forecast-observation-captures `
  --report work/forecast-observation-output-001/report.json `
  --output work/forecast-diagnostic-001.json `
  --forecast-cache work/forecast-model-cache
```

It reports median absolute error, average quantile loss and observed nominal
interval hits against the same zero-drift Gaussian baseline. The 24 planned
origins per target stay visible; invalid predictions count as failures, and
scores explicitly use only valid paired outcomes with their denominators.
`COMPLETED_DIAGNOSTIC_ONLY` means the calculation ran, not that the model passed.

The data comes from the same latest-vintage captures. This retrospective check
is not admitted PIT data, an untouched holdout, a prospective experiment or
production approval. Pretrained training overlap and historical release vintages
remain unaudited; observed interval hits do not certify future calibration.
On 2026-10-11 the private run produced all seven forecasts from genuine local
Yahoo captures, verified the pinned weight SHA256, and took 3.924 seconds for
cached CPU model loading and inference in this environment. First-time downloads
are excluded from that time. The fixed diagnostic completed all 168 planned
origin-target pairs. Its comparison was mixed across targets, so no stable
advantage over the baseline is established. Real values and diagnostic outcomes
remain local; aggregate software/model-run and synthetic display evidence are
recorded in [the execution record](../reports/6b-2k-a/verification.json).

The saved issuance has origin 2026-10-09 and target 2026-10-16. After the target
session has closed and a usable capture is available, compare each preserved
forecast with `P_target / P_origin - 1` using consistently adjusted endpoint
prices. For relative targets compare `(A_target / A_origin) / (SPY_target /
SPY_origin) - 1`. Record the outcome capture and its vintage: a subsequently
revised origin price is not an original-cutoff outcome certificate. One completed
issuance provides one outcome per target, not proof of calibration or advantage.

`predictive_effectiveness=NOT_TESTED` continues to describe formal
validation status. Any real promotion still requires the unchanged research
admission and predictive-validation gates. Diagnostic JSON with real outcomes
also stays local under the publication boundary above.

## Public display example

The offline command below produces a normal example and a latest-SPY-failure
example through the same input/report path. Forecast numbers come from an
explicit `SYNTHETIC_DISPLAY_STUB_NOT_CHRONOS2`, not the real model. This generator
downloads neither market data nor model weights and accepts no real report input.

```bash
python -m runners.standalone.sentinel_forecast_example \
  --output-directory work/new-synthetic-forecast-example
```

Download [the synthetic display package](../reports/6b-2k-a/synthetic-forecast-demo.zip)
and read [browser acceptance](../reports/6b-2k-a/visual-acceptance.md). The package
demonstrates presentation and failure handling; it is not a usable market forecast.
