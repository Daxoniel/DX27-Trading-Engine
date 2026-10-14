# INTRA-P0: Alpaca Paper connectivity check (read-only)

Scope: **paper account, clock and asset metadata only**. This diagnostic does
not collect bars, evaluate ORB signals or create, cancel or modify orders.
It does not activate production or change frozen Sentinel code. The API host
is hard-coded to https://paper-api.alpaca.markets, with a GET-only allowlist.
It ignores APCA_API_BASE_URL; no live host or custom broker URL is supported.
A successful check is *not* authorization to submit paper or live orders.

## One-time setup (PowerShell on Windows)

1. Create an Alpaca **Paper Only** account (no real funds) and turn on MFA.
2. Open the Paper Trading dashboard, create a paper API key and keep both parts
   private. Do not enter the keys in ChatGPT, Codex prompts, GitHub or screenshots.
3. From the DX27 checkout, install the repository once:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[test]"
   ```

4. In your local PowerShell only, set **paper** credentials (these assignments
   are placeholders; use your own secrets and don't paste terminal history):

   ```powershell
   $env:APCA_API_KEY_ID = "<YOUR_PAPER_KEY_ID>"
   $env:APCA_API_SECRET_KEY = "<YOUR_PAPER_SECRET>"
   .\.venv\Scripts\python.exe -m dx27.adapters.alpaca.paper_probe --symbols SPY,QQQ,IWM
   ```

For stronger local secret handling, use an OS-protected secret manager to
populate the two environment variables rather than retaining plaintext in
PowerShell history, profiles, files or screenshots.

The command prints only minimized account readiness and market-clock status,
plus whether the requested assets exist/trade. It deliberately excludes account
number, ID, balance, cash, positions, API keys and HTTP error bodies.
It outputs no secrets to the repository.

**Expected:** environment ALPACA_PAPER_ONLY, connected true,
execution_enabled false, statuses for three assets. Exit code 1 on missing
credentials, HTTP error, timeout, malformed payload or invalid symbols.
A rejected request does not silently switch to live endpoints.

Offline unit verification:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_alpaca_paper_probe.py
```

## Hard gates before paper order execution

- Keep the INTRA-1A research and ledger separate from actual execution.
- Free Paper Only accounts receive IEX-only real-time data, not full SIP.
  The existing historical 1-minute downloader is explicitly SIP and ends
  at least 15 minutes old. Never silently swap IEX bars into SIP research
  or claim IEX-only volume equals market-wide RVOL.
- First implement audited, persistent, **paper-only** order state:
  deterministic client_order_id, submit/retry/lookup/cancel/reconcile,
  restart recovery, partial fills and network-error idempotency.
- Enforce no orders until complete required bars and a data-source gate
  explicitly passes. Record feed ID, timing, failure and uncertainty.
- Keep an independent kill switch OFF by default; require explicit
  opt-in for paper order testing. Hard-deny live endpoints and real funds.
- Paper fills are hypothetical; live impact, queueing, latency and fees
  differ, even if paper trading appears profitable.

See https://docs.alpaca.markets/us/docs/paper-trading and
https://docs.alpaca.markets/us/docs/market-data-faq.
