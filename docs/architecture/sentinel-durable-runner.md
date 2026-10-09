# 6B-2I-3A — Durable Pilot Runner & Recovery Validation

Windows deployment is **PASS_USER_REPORTED_ACCEPTANCE** as of 2026-10-09.
The user confirmed reboot recovery and actual email delivery; native tests were
not independently observed by Codex. See the archived deployment acceptance record.

The existing 2026-10-08 through 2026-11-04 protocol, clock profile, four polling
slots, 20-session denominator and coverage thresholds remain byte-identical.
PR #32's status was corrected separately: temporary PID/heartbeat observations
prove instant liveness only. The temporary runner remains best-effort fallback
until an explicit, single-writer handoff to the accepted target.

## Infrastructure implementation

The collector lock uses POSIX flock or Windows byte-range locking. Windows gets
an explicit tzdata dependency. Complete captures are fsynced in a staging folder
then published as a directory; interrupted staging bytes never become evidence.
Bindings/job files use atomic, exclusive hard-link publication (local NTFS/POSIX),
so interruption cannot expose a half-written final JSON. Existing IDs, bytes and
actual capture times stay unchanged. Corrupt committed evidence still fails
verification; it is not silently repaired or discarded.

`store_migration` exports a quiesced, verified raw journal and restores it only
into a new directory. It preserves all capture/binding/job/report bytes and
checks file hashes, record seals and source IDs. Process-local heartbeats/locks
are excluded. Unsafe archive paths, unexpected members, duplicates, overwrite
attempts and altered checksums fail closed. The manifest captures a specific
checkpoint; it does not authorize divergence between two active host copies.
A final export must be refreshed if the temporary host records new data before
handoff. No public GitHub upload of raw series is performed.

The OS schedules `supervised_runner`, which starts the unchanged polling worker,
retains collector logs, checks heartbeat and job deadlines, and exits with failure
if the child dies or hangs. Windows Task Scheduler restarts a failed task and starts
it after boot, using stored OS account credentials. Pending native acceptance
includes logged-out execution and ensuring no orphan worker survives task stop.
Neither a task registration nor a preflight can self-certify durability.

External monitoring receives an HTTPS heartbeat every minute, configured for a
2-minute period plus 3-minute grace. An email integration belongs to the user's
monitoring account, not this temporary environment. Missing pings can alert even
when the PC is offline. New MISSED events and detected worker failures issue a
failure signal. Ping tokens remain private; raw series are never sent to the
monitoring service. Delivery failure is recorded and the external missing-ping
alarm remains an independent signal. Heartbeat staleness allows up to 15 minutes
for bounded provider fetch/report work; polling/cutoff overdue checks separately
use an 8-minute diagnostic threshold. These health thresholds do not extend
scientific polling grace or observation eligibility.

## Acceptance that must happen on the real PC

- Local persistent NTFS storage, accurate clock and identical frozen calendar.
- Network access to the real providers and monitoring endpoint, with TLS intact.
- Windows task runs while logged out and recovers automatically after reboot.
- Restart and forced child-failure tests recover one active worker, with unchanged
  store hashes, capture IDs and original cutoff snapshot identities.
- Actual alarm and recovery email received at the user's chosen address after
  stopping the task and allowing the external grace to elapse.
- PC stays powered, awake and connected throughout the pilot; external checks
  remain armed. A host outage stays a missing pilot day, not a reset window.
- A byte-verified final store checkpoint is handed off while the old collector is
  stopped; the old environment never continues as a second authoritative writer.

The Linux workspace can test migration, lock release after process death,
atomic publication and causal polling. It cannot prove Windows task registration,
reboot survival or email delivery on the user's computer. Native recovery/email
acceptance is user-reported in deployment_acceptance.json; optional diagnostic
subtests without distinct evidence are listed there. 6B-2J real validation remains blocked.

See [Windows operation guide](../operations/sentinel-windows-pilot.md). After 3A
acceptance, a separate 6B-2J-A protocol/synthetic task can proceed while Track A
continues collecting; it cannot certify real effectiveness or production readiness.
