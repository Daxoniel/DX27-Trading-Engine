# MLP2: source mapping correction and daily candidate diagnostic

This is a retrospective research adaptation of the long pullback branch, not
Martin Luk's complete discretionary method. MLP1 code, protocol and historical
results remain frozen. No orders or profitability claims are authorized by this
diagnostic. Protocol: [protocol-v2.json](protocol-v2.json).

## Source audit

| Primary source | What it supports | Implementation and remaining approximation |
|---|---|---|
| [First-person guest post, February 2025](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons), section 2 | Sector attention comes from scanning/strength-list changes, followed by monitoring pullbacks. | Count sector leaders before testing support proximity. Two peers, fixed broad sectors and static leadership are our proxies; this does not implement new theme emergence or upgrades. |
| [TraderLion interview](https://www.youtube.com/watch?v=VKNEJA5r8zw&t=3478s), approximately 3478–4292 seconds | Daily EMA/support and anchored VWAP inform pullback location; confluence can strengthen a setup. | EMA9, EMA21 and daily AVWAP are alternative levels. Remove mandatory 0.5% separation between two indicators. A daily typical-price AVWAP anchored to the highest high in 60 sessions remains our approximation, not his exact discretionary anchor. |
| [Same interview](https://www.youtube.com/watch?v=VKNEJA5r8zw&t=7310s), approximately 7310–7498 seconds | Weak downtrends can fail; he discusses higher lows in a base and first pullbacks within it, and repeated stopouts. | Delete the EMA21-touch-since-last-cross veto. That test does not identify bases. MLP2 does NOT claim to identify first pullbacks; the existing rolling five-session higher-low proxy remains. |
| [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), stock bar trade conditions | Daily and minute aggregation can treat trade conditions differently. | Use the vendor 1Day OHLCV consistently for both scanners, with effective-date split adjustment. Daily volume is not labelled RTH volume. Do not preselect with one price definition and certify a different definition as exhaustive. |

The interview was checked through timestamped transcript passages, not a claim
that all chart footage was independently watched. These sources describe a
method; they do not establish expected profitability for this implementation.

## Exact scope

Leadership retains MLP1 price, liquidity, ADR, EMA trend, momentum and rolling
higher-low conditions, but no support-proximity gate. Candidates then require
at least two leaders in their sector and proximity to at least one known level.
The intraday adapter checks levels highest first, with alphabetical ties, and
accepts the first satisfying the existing recovery/stop-distance checks. It
never chooses a level by subsequent return. Signal IDs identify MLP2 and hash
the original plan, not a temporary modified support plan.

All unchanged numerical thresholds are DX27 engineering choices, including ADR
5%, momentum 30%, $20M daily dollar volume, 0.5% per-trade account risk, and the
two-hour entry window. One intent per symbol per session is retained despite
Luk allowing reentries; MLP2 is deliberately incomplete. No parameter grid or
selection by profit is performed.

## Reproduce candidate coverage

Reuse the private cache documented in [history.md](history.md):

```sh
python research/martin-luk/scan_history_v2.py --root work/mlp1-history --output work/mlp2/coverage
python -m unittest discover -s research/martin-luk -p 'test_*.py' -q
```

All 4,002 archived cohort names are accounted for across the 172 sessions.
Both scanners receive identical daily snapshots after a common necessary-filter
stage using their unchanged price/liquidity/ADR conditions on the SAME adjusted
vendor daily values. Common failures are explicitly counted, not silently
dropped. This optimization does not reuse the old MLP1 preselection or a
different price convention; an equivalence test covers both scanners. A name
with missing or invalid required history also has an explicit exclusion.
There is no current asset-status filter.
The prior 160 exchange sessions are required; five-minute bars are not required
to establish daily warmup. The fixed archived name filter is not proof of
security type, historical tradability, dynamic membership or sector changes.

The cache contains final revised vendor records. `available_at` in the daily
snapshot is a synthetic retrospective knowledge clock, not verified receipt
time. Corporate-action records likewise lack verified first availability.
2025 outcomes have already been seen: this is not an independent holdout.

Private plans contain vendor-derived prices and remain in `work/`. Public
results contain counts, input/code hashes and limitations only. Candidate
coverage is not trade frequency, win rate, profitability or evidence sufficient
to enter Paper. The next stage needs a frozen execution protocol, intraday
coverage and a single shared-portfolio replay with auditable fills/cash/actions.
