# Authentication

## Model: RBAC issues, Ticketing verifies

`app.rbac` (`AuthService`) is the **sole issuer** of JWT access and refresh tokens (HS256, `python-jose`, `JWT_SECRET_KEY`). `app.ticketing` has no login/signup/refresh endpoint of its own and no `create_token`-shaped function anywhere in its code — it only decodes and validates against the same secret. This was originally a cross-process trust relationship (two services, two `.env` files that had to be kept byte-identical); it's now enforced within one process reading one `.env` file, but the conceptual boundary is unchanged.

## Token contents

The access token carries:
- Standard claims: subject (`user_id`), `type` ("access"/"refresh"), expiry.
- `permissions` — the caller's full effective permission list (role default ∪ active unscoped overrides).
- `scoped_permissions` — a `dict[permission_name, list[ticket_id]]` for ticket-scoped overrides only, deliberately excluded from the flat `permissions` list.
- `name`, `role_id`, `category_id`, `category`, `permission_version` — added later, purely to let `app.ticketing`'s `get_current_user` skip a database round trip on a cache hit.

All of the above degrade gracefully if absent (a pre-upgrade token) — never a hard failure, just a fallback to the slower/older code path.

## Password handling

Bcrypt via `passlib` (`passlib[bcrypt]==1.7.4`, `bcrypt==4.0.1`). No evidence of a password-strength policy enforced server-side was found in this pass — **not confirmed** whether one exists client-side only.

## Session model

Stateless JWTs — there is no server-side session table, and logout is audit-only (`auth.logout` event, no token invalidation mechanism). **A compromised/leaked token remains valid until it expires** — there is no revocation list. Rotating `JWT_SECRET_KEY` is the only way to force a global logout, and it's treated (correctly) as a disruptive, deliberate action, not a routine config change.

## The RBAC session cache and its security implication

`app/core/rbac_cache.py` reconstructs a transient `User` from JWT claims on a cache hit, without re-checking `is_active` against the database. A user deactivated mid-session can continue acting on cache-hit requests for up to `RBAC_CACHE_TTL_SECONDS` (default 30s) — the cache-miss path (which does check `is_active` and the live `permission_version`) is what eventually catches this, not an immediate revocation. This is a real, small, deliberate window of staleness, not a bug.

## SSE authentication — a deliberately different mechanism

`GET /notifications/stream` uses `get_current_user_sse`, reading the token from a `?token=` query parameter rather than an `Authorization` header, because the browser's native `EventSource` API cannot set custom headers. This dependency opens its own short-lived DB session rather than holding a request-scoped one for the connection's entire (potentially hours-long) lifetime — a deliberate scalability choice, not an oversight. **A token in a query string is more exposed than one in a header** (URL logging, browser history, referrer leakage) — this is an accepted tradeoff for this specific endpoint, not something to generalize to other routes.

## Unauthenticated endpoints — by necessity, not oversight

`POST /api/mail/incoming`, `GET /api/mail/incoming`, `POST /emails/incoming` accept no JWT at all (Graph/relay can't present one the way a browser session can). Integrity is enforced via Graph's own `clientState` match rather than a bearer token. **Whether any network-level protection (IP allowlisting, a reverse-proxy shared secret) sits in front of these in production is not confirmed** by this documentation pass — verify with whoever manages production infrastructure.

## Related
[03-business-workflows/authentication/login.md](../03-business-workflows/authentication/login.md), [authorization-rbac.md](authorization-rbac.md).
