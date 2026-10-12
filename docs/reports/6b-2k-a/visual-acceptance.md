# Five-session experimental forecast display acceptance

Chromium rendered the synthetic normal page, the synthetic latest-SPY-503 page
and the private real Chronos-2 page at 1440×1100 and 390×844. All had seven
forecast rows, readable disclosure, working forecast details and table scrolling.
The mobile document remained 390 px wide. Horizontal overflow is contained in
the tables rather than the page. Browser policy and inherited proxy were retained.

The failed-SPY example displays unavailable SPY and all three SPY-relative targets;
RSP, QQQ and IWM remain available. It does not reuse an earlier successful SPY
capture. Both examples visibly disclose synthetic input and unvalidated intervals.

These public screenshots use the deterministic display stub, **not Chronos-2
predictions**:

- [Normal desktop forecast](visual/healthy-desktop-forecast.png)
- [Normal mobile forecast](visual/healthy-mobile-forecast.png)
- [Failed-SPY desktop forecast](visual/degraded-desktop-forecast.png)
- [Failed-SPY mobile forecast](visual/degraded-mobile-forecast.png)

[Structured browser evidence](visual-acceptance.json) records dimensions and
source hashes for all three displays. Real screenshots and reports stay private.
Display acceptance establishes presentation, not predictive accuracy. Download
the [synthetic offline package](synthetic-forecast-demo.zip) to inspect its HTML.
