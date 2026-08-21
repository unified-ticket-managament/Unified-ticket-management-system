# Authorization (RBAC Enforcement)

**This is the single most important security fact about this codebase: enforcement is real and thorough in the Ticketing domain, and historically thin (partially fixed) in the RBAC domain.** Treat every claim below as domain-specific — "RBAC has weak enforcement" does not mean "the whole system has weak enforcement."

## Ticketing domain (`app.ticketing`) — real, layered enforcement

`app/ticketing/services/access_control.py` centralizes:
- Role-name constants: `AGENT_ROLE_NAMES`, `SUPERVISOR_ROLE_NAMES`, `TEAM_LEAD_TRANSFER_ROLE_NAMES`, `CATEGORY_SCOPED_ROLE_NAMES`, `GLOBAL_INBOX_ROLE_NAMES`, `ESCALATION_TAB_ROLE_NAMES`, `DUMMY_MAIL_ROLE_NAMES`, `CLOSE_REOPEN_BYPASS_ROLE_NAMES`.
- Real permission-claim checks: `has_permission`/`has_permission_for_ticket`/`ensure_has_permission`, reading the JWT's `permissions`/`scoped_permissions` claims — a decode-only check, never a fresh call back into RBAC.
- Category/client-ownership scoping: `ensure_agent_can_view_ticket`, `ensure_account_manager_owns_ticket_client`, `ensure_agent_can_act_on_ticket` (with escalation-freeze awareness).

A 2026-07-14/15 compliance audit found and fixed several real gaps here too (a missing `await` that silently disabled attachment-upload authorization entirely; an unconditional Team-Lead close/reopen bypass; missing Account-Manager-ownership checks on several mutating actions) — see [15-architecture-decisions](../15-architecture-decisions/README.md).

## RBAC domain (`app.rbac`) — historically authentication-only, partially hardened

**Before the 2026-07-14/15 audit, there was no generic `require_permission`-style dependency anywhere in this backend** — almost every route only checked `Depends(get_current_active_user)`. Any authenticated user could, in principle, call almost any endpoint regardless of role or permission.

**Confirmed current state** (from direct route inspection in this pass): most Users/Roles/Permissions/Categories/Audit-Logs routes now DO carry an explicit `ensure_has_permission(...)` check — a real, positive finding this documentation pass confirmed that some historical notes may understate. Specifically:
- `POST/GET/PUT/PATCH /users*` — gated by `user:create`/`user:view`/`user:update`/`user:disable`.
- `POST/GET/PUT/DELETE /roles*` and `/roles/{id}/permissions` — gated by `role:*`/`permission:view`/`permission:update`.
- `/audit-logs` — a **mix**: `GET .../{id}` and `.../user/{user_id}` use the real `audit:view` permission; the list/create/delete endpoints use a **hardcoded role-name string check** (`current_user.role.name == "Super Admin"`) instead — a real, confirmed inconsistency (see [07-api/organization-audit.md](../07-api/organization-audit.md)).
- `permissions.py`'s create/update/delete routes still have **no explicit permission check beyond authentication**. `categories.py`'s create/update/delete routes (and the new member-management endpoints) gained a real `category:create` permission check on 2026-08-21 — no longer part of this gap.

**The one deliberate, pre-audit exception**: `POST/GET/DELETE /users/{id}/permission-overrides` — real authorization was already enforced *inside the service* (`PermissionOverrideService.ensure_can_manage_overrides`) before the wider audit happened.

## What this means practically

- Don't assume every RBAC route is unprotected — verify the specific route in [07-api](../07-api/README.md) or the source before making a security claim.
- Don't assume every RBAC route is protected either — `permissions.py` genuinely isn't, beyond requiring a valid login. `categories.py` was fixed on 2026-08-21 (see above) and is a real example of this gap being closed over time, not just documented.
- The frontend's own role-based hiding (`PermissionGuard`, page-level role allowlists) is a real UX control but **not a security boundary** for the routes still gated by authentication alone — a direct API call bypasses it entirely.

## Permission model summary

- **Role defaults**: `role_permissions` — the baseline bundle.
- **Personal overrides**: `user_permission_overrides` — additive only, optionally ticket-scoped, soft-revocable.
- **Permission requests**: a request/approval workflow addressed to one specific person, never a role — see [04-functional-modules/rbac-authorization.md](../04-functional-modules/rbac-authorization.md).

## Related
[04-functional-modules/rbac-authorization.md](../04-functional-modules/rbac-authorization.md), [16-known-limitations/technical-limitations.md](../16-known-limitations/technical-limitations.md), [15-architecture-decisions](../15-architecture-decisions/README.md).
