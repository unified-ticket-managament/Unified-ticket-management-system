# ADR-002: RBAC Issues Tokens, Ticketing Verifies Only

**Status**: Accepted (implemented, in production use)

## Context

Before the backend consolidation, RBAC and Ticketing were two separate deployable services. A user authenticating against one needed their identity trusted by the other, without a second login.

## Problem

How should identity and session state be shared across two independently-developed services (now: two modules in one process)?

## Options Considered

1. **Each service manages its own sessions** — would require a user to log in twice, or a complex SSO handoff.
2. **A shared session store** (Redis, a database table) both services read.
3. **One service is the sole JWT issuer; the other verifies against the same shared secret, with no independent login capability of its own.**

## Decision

Option 3 — `app.rbac` (`AuthService`) is the sole issuer of access/refresh tokens; `app.ticketing` has no login/signup/refresh endpoint and no `create_token`-shaped function anywhere in its code.

## Reason

This requires no shared session infrastructure (no Redis dependency for identity itself) and no synchronization between two independent stores — a stateless JWT, verified against one shared secret, is sufficient. It also cleanly reflects the actual business ownership: RBAC owns "who is this person and what can they do," Ticketing only needs to consume that answer.

## Trade-offs

- **Cost**: `JWT_SECRET_KEY` must be identical everywhere both domains run — before the process merge, this meant keeping two `.env` files in sync (a real historical operational risk); now it's moot within one process, but the same secret must still match across every deployed instance of that one process (Render vs. EC2 vs. local, each with their own instance-appropriate value).
- **Cost**: no server-side session invalidation — logout is audit-only; a compromised token remains valid until expiry.
- **Benefit**: `app.ticketing`'s `get_current_user` can reconstruct a full user object from JWT claims alone on a cache hit, avoiding a database round trip entirely for most requests (see [ADR reasoning connects directly to the RBAC cache design](../05-technical-architecture/backend-architecture.md)).

## Consequences

Every claim added to the token (`permissions`, `scoped_permissions`, `name`, `role_id`, `category_id`, `category`, `permission_version`) had to be designed to degrade gracefully for a token minted before that claim existed — a real, deliberate backward-compatibility discipline that shows up throughout the codebase's history of adding new claims.

## Related Components

`app/rbac/services/auth_service.py`, `app/dependencies/auth.py`, `app/core/rbac_cache.py`.
