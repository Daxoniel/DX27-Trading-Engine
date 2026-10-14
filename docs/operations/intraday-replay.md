# Run INTRA-1A

Offline transaction ledger; no broker orders. Keys are needed for real downloads,
not the synthetic acceptance run.

Historical SIP and Q1 replay have now passed [real-data acceptance](../reports/intra-1a-real/validation.md).
Paper-account read-only connectivity passed after the environment domain binding
update on 2026-10-14. Realtime SIP and order execution remain separate checks. See the [P0–P3 roadmap](../architecture/intraday-delivery-roadmap.md).

## Install and demo

From a checkout, with Python 3.11 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.cli demo --output work\intra-1a-demo
```

Linux uses `.venv/bin/python`. The demo creates labeled synthetic SPY/QQQ/IWM
minutes covering a regular and Thanksgiving early-close session. Its PnL is
software evidence, not a market result.

Open `work/intra-1a-demo/report/report.md`. Inspect fills.csv, trades.csv,
equity.csv, daily.csv, decisions.csv and data-quality.csv. summary.json should
show COMPLETE_REPLAY, accounting_reconciled=true, performance_admissible=false
for synthetic data, and production_enabled=false. Buys occur after their
decision times. Repeated runs require a new output directory.

## Historical download

Inject APCA_API_KEY_ID and APCA_API_SECRET_KEY through environment configuration.
Do not put keys in committed JSON, command arguments, reports or chat.

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.cli download --symbols SPY,QQQ,IWM --start 2025-01-01T00:00:00Z --end 2025-04-01T00:00:00Z --output work\intraday-data\2025-q1.csv
```

The adapter requests old SIP explicitly with raw adjustment. End is exclusive
after normalization and must be at least 15 minutes old. Keep the CSV and its
.raw.jsonl/.metadata.json sidecars together. Errors, zero rows, repeated page
tokens or invalid data do not yield successful datasets. There is no IEX fallback.
Authenticated access/account eligibility still need validation. Real-time SIP
and broker permissions are separate later requirements.

## Replay

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.cli replay --input work\intraday-data\2025-q1.csv --config examples\intraday\intra-1a-config.json --decision-start 2025-02-01 --output work\intra-1a-2025-q1
```

Earlier sessions warm indicators without orders. Imported CSV schema:

```csv
symbol,timestamp,open,high,low,close,volume
SPY,2025-11-26T14:30:00+00:00,100,101,99,100.5,10000
```

Aware timestamps label minute starts; the runner builds complete five-minute
features. CSV without source metadata remains unverified. Absent leading/trailing
days require declared bounds to detect. Do not mix IEX/SIP volume. General stock
studies need separate historical universe and corporate-action checks.

Exit codes: 0 complete modeled replay/download; 2 incomplete report written;
1 invalid config/input or download failure. Incomplete results keep modeled
cash/positions while aggregate PnL/drawdown are null. Code 0 is not effectiveness
approval. Config defaults are engineering assumptions to review against the
account/broker. Gaps can exceed risk budgets; NBBO queues/impact are not modeled.

## Historical Shadow Mode

Continue with the same historical input using the [recorded Shadow runner](intraday-recorded-shadow.md).
It records minute batches and resumes a matching SQLite journal without duplicate
hypothetical orders. Credentials and realtime SIP access are not required.

## Offline verification

### Optional opening volume filter — INTRA-1B

Use the same sealed minute CSV and declared decision period:

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.cli replay --input work\intraday-data\2025-q1.csv --config examples\intraday\intra-1b-config.json --decision-start 2025-02-01 --output work\intra-1b-2025-q1
```

The example enables `opening_volume` with `lookback_sessions=20` and
`minimum_rvol=1.0`. Selection is available only after all 30 opening minutes;
the preceding 20 scheduled openings must all be valid. Inspect selection.csv
for all eligible and rejected symbol/session rows, including warmup. This
threshold is not calibrated to the Q1 result. Baseline config leaves it disabled.
See [the precise selection contract](../architecture/intraday-opening-volume.md).

### P0 paper-account probe

Configure the intended paper-account credentials for `paper-api.alpaca.markets`
as well as the separate data binding. Never copy key values into config or chat.
Run locally on Windows or with `.venv/bin/python` on Linux:

```powershell
.\.venv\Scripts\python.exe -m dx27.adapters.intraday.account_probe --output work\p0-paper-account.json
```

This issues only GET /v2/account, /v2/clock and /v2/positions. It never submits
orders and omits credential/account identifiers from its JSON. Exit 0 means
all three read-only responses validated; exit 2 means missing credentials,
authentication/network/schema failure. Existing output paths are refused.
CONNECTED_READ_ONLY does not verify live feed or order permission. HTTP 401
requires checking account credentials/domain binding; it does not prove which
one failed. Automatic ordering remains disabled.

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_intraday_data.py tests/unit/test_streaming_breakout.py tests/unit/test_simulated_execution.py tests/integration/test_intraday_ledger.py
```

CI runs intraday checks/demo on Ubuntu and Windows. Local Linux success does not
certify Windows CI. See [precise architecture and limitations](../architecture/intraday-replay-ledger.md).
