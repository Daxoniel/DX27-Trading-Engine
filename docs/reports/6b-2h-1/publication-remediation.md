# PR #36 publication repair

The withdrawn ZIP did contain raw source payloads: 13 Yahoo Chart v8 ETF
responses, one Cboe VIX CSV, five FRED CSV responses and five FRED metadata pages.
The earlier assertion that public availability permitted publishing this package
was incorrect. The package also contained real-series endpoint values in its
audit, so simply deleting the payload directory would not be enough.

The replacement public artifact contains synthetic observations, code, source
links, hashes and aggregate verification results. It contains no original
response payloads, real-series history, endpoint prices or real market values.
Locally sealed captures remain separate from the public artifact. The Windows
pilot and all frozen research artifacts are outside this repair.

Withdrawn commit: `3fdca97aa516ba446cd67c7933bb3ced4a0cb4c7`.
Withdrawn archive blob: `f2148172819a3cd2ca6cd071f7b583e92e704636`.
Withdrawn archive SHA256: `c1f7f82a69f52aa19fe522a7c17eb0d413050385c880f194c62a7446133af331`.

The sole unmerged PR commit was replaced, so the restricted payload is
removed from the current PR branch's reachable history without rewriting main.
This does not establish erasure of GitHub's old commit objects, pull-request
references, CDN caches, clones or forks. The repository administrator may need
to contact [GitHub Support](https://support.github.com/contact) with the withdrawn
commit/blob/archive identifiers for removal of retained hosted copies. No such
support request or final hosted-object erasure is claimed here.

### Hosted-object status

A HEAD-only check on 2026-10-10 confirmed that the withdrawn current-branch URL
returns HTTP 404, while the URL pinned to the withdrawn commit still returns HTTP
200 with the original archive length (1,050,255 bytes). No payload was downloaded
in that check. Hosted erasure is therefore **PENDING_GITHUB_SUPPORT**; branch
history repair alone has not completed it.

A repository administrator can send the following request through GitHub Support:

> Please remove retained hosted copies or cached references of a withdrawn file
> in Daxoniel/DX27-Trading-Engine. The file is
> docs/reports/6b-2h-1/sentinel-observation-2026-10-09.zip in commit
> 3fdca97aa516ba446cd67c7933bb3ced4a0cb4c7, blob
> f2148172819a3cd2ca6cd071f7b583e92e704636. It unintentionally bundled finance
> provider responses whose public redistribution permission we have not established.
> The unmerged branch has been replaced and no longer reaches this commit/blob,
> but the raw URL pinned to that old commit remains available. Please advise on
> removing the retained hosted object and associated cached views.

This is a prepared request. No request has been sent and no provider permission
or completed GitHub purge is asserted.
