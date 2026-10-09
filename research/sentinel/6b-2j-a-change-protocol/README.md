# 6B-2J-A — Protocol pre-registration

Design prepared for review. `protocol.json` inherits the frozen G evaluation exactly
and fixes two candidates, input/reset semantics, candidate selection and synthetic
case/seed plans. `references.json` is an additive task-specific reference supplement;
the original sensor reference library and links are not rewritten.

`protocol_lock.json` seals these files and the parent. This is a design lock, not
a final candidate freeze. Synthetic execution is NOT_RUN, real validation is
BLOCKED_DATA and production remains disabled.

Next: 6B-2J-B implements and verifies synthetic replay after this protocol review.
See `docs/architecture/sentinel-change-research.md` for rationale.
