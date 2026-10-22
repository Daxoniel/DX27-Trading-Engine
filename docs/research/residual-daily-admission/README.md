# DE1 daily evidence gate

This connects a native AA1 pre-open decision to fresh RC1 daily-source evidence and produces eight RS1 price proposals without writing account journals. It supplies a real GET-only capture path. Existing strategy parameters and the prior full-exposure drawdown FAIL remain unchanged.

The formation seal retains the reviewed inputs, rank hashes, full immutable capture inventory and original journal heads. Later days verify the separately known seal hash, unchanged evidence and those heads as ancestors in fully replayed/audited current journals. Each execution cycle needs a new seal. Local hashes/times do not authenticate providers, externally attest timestamps or replace documentary judgment.

Daily capture starts at least 20 minutes after XNYS close and ends before the next XNYS open. The administrative buffer accommodates delayed free data; it is not a signal or proof of final official-close publication. Capture fetches raw/adjusted bars, complete actions and metadata for the exact held/target union. Prices/actions keep canonical archived symbols; aliases apply only to metadata. Admission checks every retained close in the current continuous holding spell using original decimal tokens, including sub-float changes. Any returned action, changed UUID, incomplete review, missing price or restatement blocks admission. No invented split/dividend accounting or automatic liquidation.

All CLI modes use the actual clock, with no clock override. Before the first formation they return blocked without reading supplied evidence or opening a transport. Every output must be new and remain under ignored work/. Raw bodies, identities, per-name rankings, reviews and detailed proposals stay private.

Operational sequence:
1. Run cli.py preflight --output work/NEW-preflight.json.
2. Within formation window, run cli.py seal --capture work/FORMATION --reviews work/formation-reviews.json --registry work/residual-capture/registry-1/registry.json --output work/NEW-seal.json.
3. After the daily close buffer, run cli.py capture --day YYYY-MM-DD --seal work/NEW-seal.json --seal-sha256 PRINTED_CANONICAL_HASH --registry work/residual-capture/registry-1/registry.json --ledgers work/CURRENT-heads.json --output work/NEW-daily.
4. Run cli.py checklist with the seal/hash/registry arguments, --capture work/NEW-daily --output work/NEW-pending. Templates approve nothing.
5. Retain completed documentary review files and their referenced sources directly inside the daily capture directory; create a separate review manifest listing their path/SHA256 refs and daily manifest hash. Review after the final response.
6. Run cli.py assess with the seal/hash/registry arguments, --capture work/NEW-daily --reviews work/daily-reviews.json --output work/NEW-private-proposal.json.

All commands are prefixed with python research/residual-daily-admission/. The seal hash is the printed SHA256 of canonical JSON without the output newline, not the hash of the newline-terminated file. Keep it separately. The current-head bundle follows existing root/heads schema; derive heads from replay, never guess or change them to bypass stale evidence. Nonempty actions need a separately registered accounting policy and stay blocked here.

Thirteen new tests cover native formation-to-daily admission, a later holding period, full-spell/sub-float restatements, source/query/UUID tampering, reviews, action pagination, stale heads/cycles and time bounds. Parent suites run separately on Ubuntu and Windows. rehearsal.json is explicitly synthetic with all detailed evidence retained privately. preflight.json uses the actual clock. Neither reports strategy returns or broker fills.

Before real-source journal appends, a guarded commit adapter still needs fresh proposal revalidation, a single-writer lock, all-account prevalidation and append-only partial receipts that forbid automatic retry. RD1 remains synthetic-only. No scheduler, paid feed purchase, account access, orders or automatic Paper promotion is included.
