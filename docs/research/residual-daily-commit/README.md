# DC1 local proxy-journal commit

DC1 adds a guarded commit path for the eight existing RS1 research journals. It independently revalidates the native DE1 evidence/proposal, acquires a common account-root lock, predicts every account before any append and verifies each written event by replay and independent audit. It changes bookkeeping only: strategy parameters, cost assumptions and the prior full-exposure drawdown FAIL remain unchanged.

The exclusive lock directory is .dc1-writer.lock at the registered account root. Every DC1 writer for that root uses it; a second writer cannot take it or remove another owner's token. There is no timeout, automatic stale-lock stealing, repair, rollback or resume. Programs that ignore the cooperative lock remain unsupported. Current heads are checked again before each append.

Each operation under dc1-operations has a hash-bound prepared receipt, eight case receipts and a completion receipt. Receipts and new event files are fsynced. Before further commits, old receipts must be complete/unchanged and their after-heads must still be ancestors of current journal heads. Daily evidence directories must remain unchanged after commit. Eight-file commits are not atomic; filesystem directory metadata is not guaranteed power-loss durable.

Any exception after operation-directory creation retains the lock and partial/incomplete evidence. Attempted case keys and confirmed case keys are distinct: an unconfirmed append may already exist on disk. Missing partial receipts do not authorize retry; an incomplete operation still blocks even if someone removes only its lock. Investigate all eight journals and retained receipts before any manual recovery; DC1 includes no recovery tool.

The actual-clock CLI has no clock override:
python research/residual-daily-commit/run.py preflight --output work/NEW-preflight.json
python research/residual-daily-commit/run.py commit --capture work/DAILY --seal work/formation-seal.json --seal-sha256 FORMATION_HASH --reviews work/daily-reviews.json --proposal work/DE1-proposal.json --proposal-sha256 FULL_PROPOSAL_HASH --registry work/residual-capture/registry-1/registry.json --output work/NEW-commit-result.json

Hashes are SHA256 of full canonical JSON without a trailing newline. FULL_PROPOSAL_HASH is the output_sha256 printed by the DE1 assess CLI, not the nested proposal_sha256 that covers only the request map. The successful private result includes next_ledger_bundle with all eight replayed heads; use that root/heads object for the next DE1 capture rather than the original initialization bundle. The CLI checks the published registry. The output must be new and outside both capture directories and the account root; it is reserved before account mutations. On failure it may remain empty: account-root operation/lock receipts are authoritative. Keep outputs, IDs, raw sources, per-name proposals and detailed ledgers in ignored work/.

Before first formation, preflight/commit return blocked before reading supplied inputs or creating a lock. After formation, preflight still performs no commit. Commit sends no network requests and reads no provider credentials. It requires explicit evidence, existing expected heads and the registered close-plus-20-minute/next-open window throughout.

Twelve new tests cover successful entry plus a held day, hash/request injection, stale duplicates, competing lock acquisition/ownership, post-write exceptions, lost completed events, receipt tampering, disk/audit failures, evidence mutation and a deadline crossing mid-commit. The retained rehearsal is explicitly synthetic: 16 appends across eight fabricated accounts over two future synthetic dates, with no prospective strategy results. The real-clock preflight is blocked; the eight actual prepared research accounts remain empty.

This appends fractional adjusted-price research proxies. It does not access Paper balances, submit orders, authenticate provider data, externally attest clocks, install a scheduler or automatically promote a strategy. DE1's identity/action review and price-vintage restrictions remain in force.
