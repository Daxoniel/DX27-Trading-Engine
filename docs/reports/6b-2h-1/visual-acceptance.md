# Browser acceptance · display and failure disclosure

The final generated pages passed actual Chromium checks at desktop 1440×1100
and mobile 390×844. They were served over normal loopback HTTP; browser policy
and the configured proxy were unchanged. This validates layout and disclosure,
not market effectiveness. All published screenshots below use synthetic data.

Chinese rendered with Noto Sans CJK SC. The desktop page has no horizontal
overflow; the mobile summary becomes one column. Main tables are 660px wide
and scroll inside a 316px container (measured scrollLeft 0 → 260). The source
section opens on click. Its seven columns fit 1116px on desktop and scroll on
mobile; capture IDs wrap within their cells. Those 10px IDs are dense trace
details, an acknowledged minor usability limit.

The newer-SPY-503 example visibly marks incomplete collection in its title, badge,
summary and coverage. Required coverage falls from 13/13 to 6/13; seven
SPY-dependent rows remain unavailable. Earlier successful captures are identified
in provenance and do not supply these values.

The locally generated real report also passed layout checks. Its screenshots
and market-valued observation records remain local; they are not in this directory.

- [Normal desktop](visual/desktop.png) · [normal mobile](visual/mobile.png)
- [Mobile table scrolling](visual/mobile-table-scroll.png) · [expanded details](visual/mobile-details.png)
- [Desktop source table](visual/desktop-sources.png)
- [Failed-latest-fetch desktop](visual/degraded-desktop.png) · [failed-latest-fetch mobile](visual/degraded-mobile.png)
- [Measured acceptance data](visual/acceptance.json)

The acceptance record hashes the exact HTML files inside the public example ZIP.
