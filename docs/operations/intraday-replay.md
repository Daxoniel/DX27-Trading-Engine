# Run INTRA-1A

Offline transaction ledger; no broker orders. Keys are needed for real downloads,
not the synthetic acceptance run.

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

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_intraday_data.py tests/unit/test_streaming_breakout.py tests/unit/test_simulated_execution.py tests/integration/test_intraday_ledger.py
```

CI runs intraday checks/demo on Ubuntu and Windows. Local Linux success does not
certify Windows CI. See [precise architecture and limitations](../architecture/intraday-replay-ledger.md).
