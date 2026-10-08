# 6B-2I-2 — Recorded Availability Capture & Source Binding Validation

The research adapter captures 19 feeds plus five FRED metadata pages. It preserves
raw response bytes, source URL/status, SHA-256 and actual UTC response-completion
`first_seen_at`. Unknown `published_at` stays null; HTTP Date, observation labels,
nominal vintages and published schedules cannot replace availability evidence.

The live Yahoo request captures two years for bootstrap; it does not fulfill
the separate 2003/2004 historical acquisition requirements.

Capture directories and initial binding records use exclusive creation. Replays
verify payload, record and binding seals and refuse calendar/protocol changes.
This is software-enforced append-only capture with tamper detection, not storage
hardware WORM or protection against an owner replacing both data and hashes.
Provider revisions retain separate captures. Binding identity uses the first
validated capture and is stable across subsequent fetches. FRED binding validation
occurs no earlier than both its data and unit metadata captures.

Yahoo validates symbol, USD, ETF type, timezone, array cardinality and OHLC bounds.
Captured adjusted close is used for price measurements. Its historical rows are
known only at actual capture time; revisions never manufacture historical vintages.
An unfinished session in a capture is permanently excluded from that capture.
Cboe/FRED date-only rows use a conservative full New York calendar-day window.
Their exact economic close clock is not approved. This may exclude same-day rows
before local midnight and prevents age-zero S qualification with this profile;
it is a profile limitation, not evidence that the provider delivers too late.
Changing this requires verified clock evidence and a separately versioned binding.

The calendar is pinned to exchange-calendars 4.13.2, 2003-01-01 through 2027-12-31.
The CLI chooses the latest XNYS close+120-minute cutoff that has actually elapsed.
It rejects future requested decisions. Full-record and cutoff-prefix snapshots
must agree. Prior S/D inputs are rebuilt at each original decision cutoff and
remain research references; reports do not acquire production priorities/events.
Operating coverage remains unapproved; download success and format validation
are not a >=95% operating coverage result. No prospective experiment starts here.

## Run and retain

From repository root, with the installed project environment:

```bash
python -m dx27.adapters.sentinel.recorded_runner --store work/sentinel-recorded
python -m dx27.adapters.sentinel.recorded_runner --store work/sentinel-recorded --replay-only
```

Retain the same store between runs and back it up. Raw series and MarketNow output
remain local; checked-in artifacts contain hashes, counts and validation status.
One-shot capture installs no scheduler. For prospective daily coverage, invoke
between actual session close and close+120 minutes, allowing fetch/retry time;
early closes follow the pinned calendar. Pre-close probes alone cannot capture
completed same-day ETF bars. Repeated captures keep revisions rather than replace
previous files. A later invocation cannot repair a missed historical cutoff.
Bootstrap decisions predating collection do not count as monitored misses. The
report counts elapsed monitored cutoffs but leaves operating coverage null until
an explicit acceptance study and source-clock validation establish it.

## Warmup and references

The decision period begins 2005-01-01; the first actual decision is 2005-01-03.
Full 252 prior measurement sessions begin 2004-01-02. Price measurements with
20-session lookback need raw prices from 2003-12-03, including endpoints. Scalar
level feeds need raw history from 2004-01-02. The generated per-feed requirements
are in `research/sentinel/6b-2i-2-recorded-capture/history_requirements.json`.
These dates specify raw history, not availability or vendor entitlement.
The prepared, unsent HY request is corrected with an explicit old/new hash record;
its original captured audit evidence is unchanged.

Reference IDs and feed mappings are in `references/recorded_capture_v1.json`, an
appendix bound to the original bibliography. Frozen G protocol and I experiment
locks are unchanged. Next: collect completed-cutoff samples, verify scalar close
semantics and HY publication/history evidence, then evaluate source admission.
6B-2J remains gated by data admission and validated S/D research effectiveness.

## 6B-2I-3 continuation

[The source-clock pilot](sentinel-source-clock-pilot.md) starts a separately frozen
20-decision collection study with isolated clock-v2 bindings and a local worker.
V1 source bindings and this bootstrap audit stay unchanged. Coverage completion
and S/D/data admission remain outstanding.
