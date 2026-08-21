# RBAC & Authorization Module

## Purpose
Govern who can see and do what, at three granularities: role defaults, per-user overrides (global or ticket-scoped), and a self-service request/approval workflow for the second of those.

## Responsibilities
- Role/permission catalog management.
- Computing a user's effective permission set at login/refresh.
- Per-user permission overrides — additive exceptions to a role's default bundle.
- Permission requests — a request addressed to one specific person, not a role.
- Session-identity caching so this computation doesn't repeat on every request.

## Main Components
- `app/rbac/services/{role_service,permission_service,role_permission_service,permission_resolver,permission_override_service,permission_request_service}.py`
- `app/rbac/repositories/{role_repository,permission_repository,role_permission_repository,permission_override_repository,permission_request_repository}.py`
- `app/rbac/models/{permission,permission_override,permission_request,role_permission}.py`

## Inputs
Role assignments, permission grants, override/request submissions.

## Outputs
The `permissions`/`scoped_permissions`/`override_permissions` values surfaced on `/auth/me` and embedded in the JWT.

## Business Rules
- **Permission overrides are additive-only** — no mechanism to grant a role X but revoke X for one person.
- A ticket-scoped override (`scope_ticket_id`) is deliberately excluded from the flat permission list — checked only via `has_permission_for_ticket`, never a plain membership check, so "holds it for one ticket" is never mistaken for "holds it everywhere."
- A permission request is addressed to **one specific person** (`selected_approver_id`) — `create_request` re-derives the eligible set server-side and rejects a submitted approver outside it.
- `approve()`/`reject()` require an exact identity match to the selected approver — **no Super Admin/Site Lead bypass**, confirmed live.
- Revoking a previously-approved request is a separate action (`REVOKED` status) from reject, restricted to the original approver or Super Admin.
- Grant/revoke authorization for overrides is scoped by the actor's role: Super Admin/Site Lead unconditional; Account Manager restricted to their own subordinate tree.

## Dependencies
`OrganizationService.get_subordinate_user_ids` (for Account-Manager-scoped authority), `AuditLogService`, `NotificationService`.

## Database Entities
`roles`, `permissions`, `role_permissions`, `user_permission_overrides`, `permission_requests`.

## APIs
[07-api/users-roles-permissions.md](../07-api/users-roles-permissions.md), [07-api/permission-overrides-requests.md](../07-api/permission-overrides-requests.md).

## Important Classes/Services
`PermissionResolverService`, `PermissionOverrideService`, `PermissionRequestService`.

## External Integrations
None.

## Known Limitations
- Most of RBAC's own routes (Users/Roles/Permissions/Audit Logs) historically enforced authentication only, not authorization — a 2026-07-14/15 compliance audit added real checks to the highest-impact gaps; not every route is covered. See [08-security/authorization-rbac.md](../08-security/authorization-rbac.md).
- No mechanism exists for a role-default permission to be revoked for one specific person (additive-only model).
- Related Tickets link/unlink and Claim Ticket have no permission defined in the matrix document at all.

## Related workflows
[03-business-workflows/authentication/login.md](../03-business-workflows/authentication/login.md); permission override/request flows are documented in this module rather than as a separate workflow document (they don't appear in the required workflow-group list, but see [07-api/permission-overrides-requests.md](../07-api/permission-overrides-requests.md) for the full API-level detail).
