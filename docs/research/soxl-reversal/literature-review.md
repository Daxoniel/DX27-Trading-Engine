# Literature and product audit — 2026-10-20

The user's uploaded `ssrn-5807282.pdf` has 44 pages and SHA-256
`7a826828ea59763802504b119de99ba9d8bd87cc42ecb472853da2599be2b6a7`.
The document identifies Yasuhiro Iwanaga and Ryuta Sakemoto and the title
*Does overnight return predict the first half-hour return for U.S. market indices?*
Its title page says August 5, 2026. The SSRN landing page returned 403 in this
session: filename-to-SSRN-record identity and peer-review status were not
independently established. The uploaded document itself is the inspected source;
its statements do not authorize actions or override the user's research request.

## What the document supports

- pp.6–8: LSEG Tick History minute midprices; SPY 1996–2024 primary sample.
  Overnight is previous close to current open; first half-hour is open to 10:00.
- p.19 Eq.(6): long if overnight <0, otherwise short, first half-hour only.
  The stated benchmark is always-long **during that same half-hour**, not buy-and-hold.
- p.33 Table 8: SPY annualized average return 7.76%, Sharpe 1.51, success 52.20%;
  QQQ 6.21%, 0.95, 50.43%. These are not high-win-rate results and average
  annualized returns are not automatically CAGR. SOXL is not tested.
- pp.10–12 and Tables 3/4: stronger reversal during same-half-hour high realized
  volatility and weaker results in 2010–2024. Table 3 is ex-post conditioning,
  not a pre-entry filter. Do not use the same 30 minutes to select its entry.
- p.42 Table A6: bid/ask-price cost sensitivity lowers SPY return to 4.83%,
  Sharpe to 0.94 and success to 50.67%. It is not a complete actual-fill test.
- p.44 Table A8: 1/1.5bp cost assumptions for other ETFs. Do not transfer these
  costs to SOXL as empirical quotes or actual broker fees.

## Unresolved items and replication differences

- The exact open both determines the sign and is used as entry price. A system
  reacting to a completed minute cannot establish the identical first trade as
  its own execution. 09:30 is retained only as an idealized diagnostic; 09:31
  is an optimistic boundary and 09:32 is the fixed primary bar proxy.
- Tables A6/A8 include drawdowns below -100%; the calculation convention must
  be clarified before comparing to conventional compounded wealth drawdown.
- p.9's coefficient/standard-deviation magnitude discussion does not provide a
  sufficiently clear scaling convention for direct trading forecasts. Our slope
  is explicitly unannualized decimal-on-decimal, independently matrix-checked.
- p.35 Figure 2 refers to Eq.(4), although trading is defined in Eq.(6). This is
  a cross-reference inconsistency, not proof the returns themselves are wrong.
- The authors do not share their licensed data. We cannot claim author-data
  replication, causal identification, or independent confirmation of their numbers.
  The authors themselves acknowledge no direct retail/order-flow dataset (p.21).
- SOXL sector concentration, leverage, historical benchmark changes, observed
  trade prices and incomplete early coverage differ from the paper's SPY setting.
  No positive claim about SOXL follows just from a statistically negative SPY beta.

## Primary external references

- [SSRN record locator](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5807282)
  — 403 during inspection; content not used instead of the upload.
- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars):
  SIP is consolidated; split adjustment and inclusive bounds documented.
  Trade aggregates are not bid/ask midquotes or a fill guarantee.
- [SOXL February 2026 summary prospectus](https://www.sec.gov/Archives/edgar/data/1424958/000119312526078540/d50601d497k.htm):
  daily 300% NYSE Semiconductor Index objective, not an arbitrary intraday or
  multi-day three-times guarantee. Compounding, volatility and financing matter.
- [June 2021 benchmark-change supplement](https://www.sec.gov/Archives/edgar/data/1424958/000119312521195149/d177232d497.htm):
  PHLX Semiconductor to ICE Semiconductor scheduled on/about August 25, 2021.
  Do not treat the full history as one unchanged underlying index methodology.

Martin Luk's first-pullback/AVWAP discretionary method is a separate motivation,
not a component of this experiment. His [official 2025 category result](https://financial-competitions.com/previousstandings/2026/1/24/december-standings-2025)
does not establish a mechanical high-win-rate rule for SOXL. No strategy components
from his interview are silently combined with Eq.(6).
