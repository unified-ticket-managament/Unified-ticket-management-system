# Authentication Module

## Purpose
Verify identity once, then propagate that identity — plus a rich, self-contained permission snapshot — across every subsequent request in both API domains without a repeated database round trip.

## Responsibilities
- Password-based login, refresh-token exchange, logout, change-password.
- Being the **sole issuer** of JWTs for the entire product — `app.ticketing` never issues or validates independently of RBAC's secret.
- Embedding effective permissions, scoped permissions, and cache-relevant identity claims directly into the token.

## Main Components
- `app/rbac/services/auth_service.py` — `AuthService`
- `app/rbac/services/permission_resolver.py` — `PermissionResolverService`
- `app/auth/jwt.py` — encode/decode
- `app/dependencies/auth.py` — `get_current_user`, `get_current_agent`, `get_current_user_sse`, shared `_authenticate_token` helper
- `app/core/rbac_cache.py` — session identity cache

## Inputs
Email + password (login); a refresh token (refresh); a Bearer JWT (every other authenticated request).

## Outputs
Access token (short-lived, `ACCESS_TOKEN_EXPIRE_MINUTES`, default 30) + refresh token (`REFRESH_TOKEN_EXPIRE_DAYS`, default 7).

## Business Rules
- A user's permission snapshot in their token is only as fresh as their last login/refresh.
- Login failure reasons are internally distinguished (`invalid_email`/`account_inactive`/`invalid_password`) for audit purposes but externally generic (401) to avoid user enumeration.
- A JWT minted before a given claim existed still decodes safely — every claim-dependent enhancement degrades gracefully rather than erroring.

## Dependencies
`shared_models.User`/`Role`, `PermissionResolverService`, `rbac_cache`.

## Database Entities
`users`, `roles`, `audit_logs` (login/logout/change-password events).

## APIs
See [07-api/auth.md](../07-api/auth.md).

## Important Classes/Services
`AuthService`, `PermissionResolverService`, `RBACCache`.

## External Integrations
None.

## Known Limitations
- `change_password` shares the same latent transient-object `db.refresh()` bug that `update_profile` had (fixed) but was **not itself fixed** in the same pass — a similarly-shaped intermittent 500 is a known suspect. See [14-troubleshooting/authentication](../14-troubleshooting/authentication/).
- No server-side session invalidation exists for logout — JWTs are stateless; logout is audit-only.

## Related workflow
[03-business-workflows/authentication/login.md](../03-business-workflows/authentication/login.md)
