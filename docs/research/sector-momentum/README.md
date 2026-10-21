# High-beta sector-relative momentum diagnostic

This preregistered pilot compares ordinary momentum and sector-relative momentum in the same fixed archived stock cohort. It is a **signal/adjusted-return proxy study, not an executable trading backtest**. No orders are sent. All results remain conditional and cannot automatically promote a Paper strategy.

[Protocol](protocol.json) freezes dates, inputs, score, beta/liquidity conditions, allocations, execution lag proxy, costs and failure policy before outcome computation. The 2025 period is already exposed and is not an independent holdout. Archived broad sector labels are not fine historical SIC industry memberships. No industry-level index performance will be substituted for this stock experiment.

The primary comparison changes only the ranking score. Both cases require beta >=1.5 estimated from 252 aligned pre-formation daily observations, minimum raw price $5 and $20m average daily dollar volume. They hold ten 10% slots, at most two per sector. Relative momentum subtracts the mean 2–12 return of other eligible same-sector peers; at least ten other peers are required. Targets form at month-end and the proxy rebalances only at the second later benchmark-session close. All remaining numbers are DX27 choices, not claimed verbatim literature rules.

Vendor adjusted closes supply a retrospective total-return proxy. They do not establish contemporaneous data publication or executable closing prices, bid/ask/depth, broker reinvestment, taxes or lot-level corporate-action accounting. The cost solver charges buys and sells on drifted notional changes using post-cost target equity. Missing held observations halt the case with no full-period return; future completeness never determines selection. No annualization of the short pilot and no claim that monthly positive intervals equal actual trade win rate.

Results and source reading notes will be added after the frozen code and input seals are published.
