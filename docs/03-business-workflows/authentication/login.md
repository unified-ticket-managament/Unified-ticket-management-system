# Login Workflow

## 1. Purpose
Authenticate a user and issue the JWT that carries their identity and effective permissions to every subsequent request across both API domains.

## 2. Trigger
`POST /api/v1/auth/login` with email + password.

## 3. Actors
Any user row in `users` (any role, including Client).

## 4. Preconditions
- The account exists, is active (`is_active = true`), and the submitted password matches `password_hash`.

## 5. High-Level Flow
Credentials → validate → compute effective permissions → issue tokens → audit log.

## 6. Detailed Workflow
1. `AuthService.login` looks up the user by email (`UserRepository`).
2. Password verified against `password_hash` (bcrypt via `passlib`).
3. `PermissionResolverService.get_effective_permissions(user)` computes `role_permissions(role_id) ∪ active_global_overrides(user_id)`, plus a separate `scoped_permissions: dict[permission_name -> [ticket_ids]]` from active ticket-scoped overrides.
4. `create_access_token` embeds `permissions`, `scoped_permissions`, `name`, `role_id`, `category_id`, `category`, `permission_version` as JWT claims (HS256, `JWT_SECRET_KEY`).
5. A refresh token is issued alongside (longer TTL, `REFRESH_TOKEN_EXPIRE_DAYS`).
6. An `auth.login` (success) or `auth.login_failed` (with `reason`) audit row is written, capturing IP where available.

## 7. Business Rules
- A user's permission snapshot is only as fresh as their last login/refresh — a permission grant/revoke mid-session doesn't reach an already-issued access token until the next one of those two events.
- Login failure reasons are distinguished internally (`invalid_email`/`account_inactive`/`invalid_password`) for audit purposes, but the HTTP response is a generic 401 to avoid user enumeration.

## 8. Decision Points
- Email not found → `invalid_email` failure reason.
- Account `is_active = false` → `account_inactive`.
- Password mismatch → `invalid_password`.

## 9. Database Changes
- Reads: `users`, `roles`, `role_permissions`, `user_permission_overrides`.
- Writes: one `audit_logs` row.

## 10. APIs Involved
`POST /api/v1/auth/login`, `POST /api/v1/auth/refresh` (re-derives the same permission snapshot).

## 11. Services / Components Involved
`AuthService`, `PermissionResolverService`, `UserRepository`, `app/auth/jwt.py` (token encode/decode).

## 12. External Integrations
N/A.

## 13. Notifications
None fired by login itself.

## 14. Audit Events
RBAC-native `audit_logs`: `auth.login`, `auth.login_failed`, `auth.logout` (separate endpoint), `auth.change_password`.

## 15. Failure Scenarios
Wrong password / inactive account / unknown email — all logged with a distinguishing reason internally, generic 401 externally.

## 16. Edge Cases
- A JWT minted before the `permissions`/`scoped_permissions`/etc. claims existed still decodes — every enhancement built on those claims falls back to its older/slower behavior rather than erroring (see [08-security/authentication.md](../../08-security/authentication.md)).

## 17. Postconditions
Caller holds a valid access + refresh token pair; the RBAC session cache (`app/core/rbac_cache.py`) has no entry yet for this user until their first authenticated request.

## 18. Relevant Source Files
- `unified-backend/app/rbac/api/v1/auth.py`
- `unified-backend/app/rbac/services/auth_service.py`
- `unified-backend/app/rbac/services/permission_resolver.py`
- `unified-backend/app/auth/jwt.py`

## 19. Example Scenario
A Staff member logs in. Their token embeds `role_id` for Staff, `permissions` from the Staff default bundle plus one active global override (say, `ticket:transfer`), and `scoped_permissions: {"ticket:editother_ticket": ["<ticket-uuid>"]}` from a ticket-scoped grant approved last week. On their first request to `app.ticketing`, `get_current_user` finds no cache entry, does a full DB lookup, and populates the cache keyed on `(user_id, permission_version)`.
