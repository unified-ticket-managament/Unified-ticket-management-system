# Rollback

**No dedicated rollback tooling or documented rollback procedure was found in this repository** for either deployment path. This page describes the mechanisms available given the actual deployment scripts, not a confirmed, tested runbook.

## Path A — EC2

- Code rollback: `git fetch` + `git merge --ff-only origin/main` means the EC2 checkout always tracks `main` — reverting requires pushing a revert commit (or force-resetting `main`, which the deploy script's `--ff-only` merge would then require manual intervention on the EC2 host to reconcile, since a force-push creates a non-fast-forward situation the workflow's own merge step can't resolve automatically).
- Database rollback: Alembic supports `downgrade`, but **several migrations in this codebase explicitly have no meaningful `downgrade()`** — e.g. `c4d6e8f0a2b4_renumber_tickets_contiguous` (a one-time data fix with nothing sensible to restore to). Check each migration between the target rollback point and current head before assuming `alembic downgrade` is safe to run blindly.
- Service rollback: `systemctl restart` after manually checking out an older commit on the EC2 host would work but is not automated by the existing workflow.

## Path B — Render

- Render's own dashboard supports redeploying a previous commit/build directly (standard Render platform feature) — this is likely the most practical rollback mechanism for this path, though it was not exercised as part of this documentation pass.
- Database rollback: same Alembic caveats as above apply regardless of hosting path — the migration history is shared.

## Rollback is safest when scoped to code, not data

Because several migrations are one-way (data-fixing migrations, enum-widening `ALTER TYPE ... ADD VALUE` which cannot be cleanly reversed), **the safest rollback in most incident scenarios is rolling back application code while leaving the schema at its current head** — a newer schema with older code is far more likely to work (given the graceful-degradation patterns documented in [02-system-architecture/architecture-principles.md](../02-system-architecture/architecture-principles.md)) than forcing a schema downgrade.

## Recommendation

This is a real gap worth closing: document (and test) an actual rollback procedure for whichever environment is confirmed to be live production, including which migrations in the current chain are safe to downgrade and which aren't.
