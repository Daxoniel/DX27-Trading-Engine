# SOXX major-earnings exclusion on the fixed SOXL model

User requested a single change: do not trade on major earnings days of SOXX
constituents. [Protocol](protocol.json) was publicly committed before this
extension's outcomes were computed. Historical event and holdings inputs were
then sealed in a separate public commit before computing filtered returns.

"Major" means five largest equity issuers in the latest **publicly filed** SOXX
portfolio snapshot, available only after its filing date. These are lagged
public disclosures, not exact daily index weights. Publication history and
company identity continuity are preserved; an older-period amendment cannot
replace a newer portfolio period. Holdings, rather than subsequently observed
event returns, determine selection.

The three fixed date conventions address the distinction between release day
and the following opening session. No entry, stop, target, allocation, gap
threshold or cost was optimized. Two actual preliminary quarterly results
releases are included; two guidance-only filings are excluded. Actual release
dates were checked in the source body instead of copying SEC reportDate or
filingDate. Upcoming earnings schedules known before entry were **not** proven.

See the [full comparison](../../reports/soxl-earnings/README.md),
[input audit](input-audit.json), [events](events.json),
[historical portfolio records](holdings-snapshots.json), and
[progress snapshot](progress.json). All original research results are retained.
The filter did not improve net outcomes and was not promoted to Paper or live.
