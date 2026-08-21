# Troubleshooting: Authentication

## Problem: `PATCH /auth/change-password` intermittently 500s

**Symptoms**: A password change fails with a 500, seemingly at random — sometimes works, sometimes doesn't, for the same user.

**Possible Causes**: The RBAC session cache returns a **transient, non-session-attached** `User` object on a cache hit (`_build_transient_user`). `AuthService.change_password` (like the now-fixed `update_profile`) may call `db.refresh(user)` on this transient object, which raises `InvalidRequestError: Instance ... is not persistent within this Session`. This is a **known, confirmed-similar, but not independently fixed** bug — `update_profile` had this exact shape and was fixed by re-fetching a real, session-attached row first; `change_password` is flagged in root `CLAUDE.md` as sharing the identical latent shape, not yet confirmed fixed.

**How to Diagnose**: Reproduce with a token whose RBAC cache entry is warm (i.e., make a `GET /auth/me` call immediately before the password change, well within the 30s TTL) — this is the condition that triggers the transient-object path.

**Relevant Logs**: Look for `InvalidRequestError` / "is not persistent within this Session" in backend logs.

**Resolution**: Apply the same fix `update_profile` received — re-fetch the real, session-attached user via `user_repository.get_by_id(user.user_id)` before mutating, regardless of whether the handed-in `user` is transient.

**Prevention**: When touching any RBAC service method that receives `current_user` from `get_current_user` and then calls `db.refresh()`/`db.flush()` on it, check whether it needs the same re-fetch pattern first.

**Escalation Path**: Not documented in this repository — establish one if needed.

**Related Documentation**: [08-security/authentication.md](../../08-security/authentication.md), [04-functional-modules/authentication.md](../../04-functional-modules/authentication.md).

---

## Problem: A permission grant/revoke "isn't taking effect"

**Symptoms**: A supervisor grants (or revokes) a permission, but the affected user's session still behaves as before.

**Possible Causes**: The RBAC session cache (`app/core/rbac_cache.py`) has up to `RBAC_CACHE_TTL_SECONDS` (default 30s) of staleness by deliberate design — the affected user's `permission_version` is bumped immediately, but their *current* cached session entry isn't proactively invalidated, only rejected on its next cache-miss check.

**How to Diagnose**: Wait 30+ seconds and retry, or have the affected user log out/refresh their token.

**Relevant Logs**: N/A — this is expected behavior, not an error.

**Resolution**: Not a bug — this is the documented, deliberate tradeoff. If a use case genuinely needs instant propagation, that would be a design change (lowering `RBAC_CACHE_TTL_SECONDS`, at the cost of more DB round trips), not a fix.

**Prevention**: Document this expected delay for support staff/end users if it causes confusion.

**Related Documentation**: [16-known-limitations/technical-limitations.md](../../16-known-limitations/technical-limitations.md).

---

## Potential Issue: `.env` secret rotation appears to have no effect

**Symptoms**: `JWT_SECRET_KEY` or another secret was changed in `.env`, but the running backend still behaves as if using the old value.

**Possible Causes**: `Settings` is `@lru_cache`d — a running process never re-reads `.env`. `--reload` only reacts to Python file changes.

**Resolution**: Fully restart the backend process (not just rely on `--reload`).

**Related Documentation**: [05-technical-architecture/configuration.md](../../05-technical-architecture/configuration.md).
