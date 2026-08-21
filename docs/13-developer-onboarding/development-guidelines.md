# Development Guidelines

Conventions this codebase actually follows, distilled from its own patterns and dated engineering history — not generic best practices.

## Layering discipline

Keep business logic in services, data access in repositories, and validation in Pydantic schemas at the route boundary. See [05-technical-architecture/application-layers.md](../05-technical-architecture/application-layers.md).

## One write path per cross-cutting concern

If you're about to write a second code path that creates a `Notification`, a `UserPermissionOverride`, or bumps a ticket to CRITICAL priority — stop and route through the existing single function instead (`NotificationService.notify()`, `PermissionOverrideService.grant()`, `EscalationService._bump_priority_to_critical`). This codebase has real, fixed bugs that came from exactly this kind of divergent second path.

## Never let the two Alembic chains couple

A ticketing table referencing `users`/`roles`/`categories` gets a real FK (RBAC-owned tables are stable, foundational infrastructure). An RBAC table referencing a ticket (`scope_ticket_id`) gets a plain, unconstrained UUID, validated in application code — never a cross-chain FK. See [06-database/relationships.md](../06-database/relationships.md).

## Idempotency for anything that "fires once"

If you're adding a new kind of threshold-crossing/breach/notification that must only happen once per event, follow the existing pattern: a unique index (possibly partial) that the write itself conflicts against (`INSERT ... ON CONFLICT DO NOTHING`), not an application-level check-then-insert.

## Always check schema freshness before debugging a "logic bug"

`alembic -c alembic_rbac/alembic.ini current` / `alembic -c alembic_ticketing/alembic.ini current`, compared against `heads`, for whichever database you're debugging against. This has repeatedly been the actual root cause of confusing SLA/escalation "bugs" in this project's history.

## Verify a fix live, not just via type-checking/unit tests

This project's own standing convention (visible throughout root `CLAUDE.md`'s feature write-ups): explicitly distinguish "type-checked and unit-tested" from "live-verified against a running backend" — the former is necessary but was repeatedly insufficient to catch real bugs (missing `await`, missing DI wiring, a stale Turbopack cache, etc.).

## Before a `git pull`/merge, commit or stash uncommitted work

A real, documented incident: a `git pull` merging several teammate commits auto-merged ~90 files cleanly via git's `ort` strategy — but several of those "clean" merges silently discarded whole uncommitted features, because git's 3-way merge only compares *committed* history, and uncommitted work was never part of that comparison at all. `git status`'s `UU` list only shows textual conflicts — it says nothing about whether your own uncommitted work survived a clean auto-merge elsewhere in the same file. **Commit (even to a throwaway branch) before pulling.**

## Don't add a new "supervisor role" or role-name constant without checking existing ones first

At least three different, **non-identical** "supervisor roles" constants exist across this codebase (`unified-frontend/src/lib/role-access.ts`'s `SUPERVISOR_ROLE_NAMES`, the standalone app's equivalent, and the real backend `app/ticketing/services/access_control.py` set). Adding a fourth without reconciling would make this worse, not better — prefer extending/fixing an existing one and noting the drift if you can't fully reconcile it in scope.

## Windows-specific process hygiene

See [13-developer-onboarding/local-environment.md](local-environment.md) for the full list — the short version: don't trust a `--reload` log line, always start the backend via the venv's own interpreter, and kill *every* python process (not just the reported PIDs) when troubleshooting a stuck port.
