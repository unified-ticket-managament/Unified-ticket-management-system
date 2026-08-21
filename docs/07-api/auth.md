# Authentication API

Source: `unified-backend/app/rbac/api/v1/auth.py` (prefix `/auth`, mounted under `/api/v1`). Service: `AuthService` (`app/rbac/services/auth_service.py`). RBAC (`app.rbac`) is the **sole issuer** of tokens for the whole product — see [08-security/authentication.md](../08-security/authentication.md) for the full trust model.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Authenticate with email/password, issue access + refresh JWTs | Public |
| POST | `/api/v1/auth/refresh` | Exchange a refresh token for a new access token | Public (valid refresh token required) |
| POST | `/api/v1/auth/logout` | Record a logout audit event | `get_current_active_user` |
| GET | `/api/v1/auth/me` | Return the current authenticated user (`CurrentUser`) | `get_current_active_user` |
| PATCH | `/api/v1/auth/me` | Update profile fields (self-service) | `get_current_active_user` |
| POST | `/api/v1/auth/change-password` | Change the caller's own password | `get_current_active_user` |

## POST /api/v1/auth/login

**Business logic**: Validates email/password against `users.password_hash`. On success, computes the caller's effective permissions via `PermissionResolverService` (`role_permissions(role_id) ∪ active_global_overrides(user_id)`, plus a separate ticket-scoped map) and embeds them into the JWT as `permissions`/`scoped_permissions` claims, alongside `name`/`role_id`/`category_id`/`category`/`permission_version` — these extra claims are what let the Ticketing domain's `get_current_user` skip a DB round trip on cache-hit requests (see [05-technical-architecture](../05-technical-architecture/README.md)).

**Side effects**: Writes an `auth.login` (success) or `auth.login_failed` (with `reason`: `invalid_email`/`account_inactive`/`invalid_password`) audit log row, capturing IP where available.

**Failure scenarios**: Wrong password, inactive account, unknown email — all return a generic 401 to avoid user enumeration (verify exact response shape against `/docs` — not independently re-confirmed at the HTTP layer in this pass).

**Related DB entities**: `users`, `roles`, `audit_logs`.

## POST /api/v1/auth/refresh

Issues a new access token from a still-valid refresh token, re-embedding a **freshly computed** permission set — this is one of the two moments (the other being login) a user's permissions actually update in their token; a mid-session permission change doesn't reach an already-issued access token until the next refresh or login (see [08-security/authorization-rbac.md](../08-security/authorization-rbac.md)).

## GET / PATCH /api/v1/auth/me

`GET` returns `CurrentUser` — includes the ten Profile-module columns (phone, DOB, alternate email, office location, department, team, language, date/time format, time zone, default dashboard — all nullable), plus `override_permissions`/`scoped_permissions`.

`PATCH` persists whichever of the nine self-service-editable Profile fields were present in the request body (`team` is display-only, never editable here). **Known historical bug, fixed**: on an RBAC-cache-hit request, `get_current_user` returns a transient, session-unattached `User` object; the original `update_profile` implementation called `db.refresh()` on it unconditionally, raising `InvalidRequestError` — a real 500 on almost any Profile edit shortly after page load. Fixed by re-fetching the real, session-attached row via `user_repository.get_by_id` before mutating. `change_password` has the identical latent shape and was **not** fixed in the same pass — treat a similarly-shaped intermittent 500 on `POST /auth/change-password` as a known suspect (see [14-troubleshooting/authentication](../14-troubleshooting/authentication/)).

## POST /api/v1/auth/change-password

Verifies the caller's current password, then updates `password_hash`. Writes `auth.change_password` audit event. Does not invalidate any already-issued token (JWTs are stateless) — only future logins use the new password.
