# Organization Structure & RBAC Audit Log API

## Reporting Managers — `app/rbac/api/v1/reporting_managers.py` (prefix `/reporting-managers`)

Real HR/people-management assignment layered on top of the Account Manager role — see [04-functional-modules/organization-structure.md](../04-functional-modules/organization-structure.md).

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/api/v1/reporting-managers` | Assign an Account Manager as Reporting Manager for a category | `org:manage_reporting_managers` |
| GET | `/api/v1/reporting-managers` | List assignments (optional `account_manager_id` filter) | `org:manage_reporting_managers` |
| DELETE | `/api/v1/reporting-managers/{mapping_id}` | Revoke an assignment | `org:manage_reporting_managers` |

`org:manage_reporting_managers` is granted to Super Admin/Site Lead only by default — assigning this responsibility is an org-design action, never self-service. No uniqueness constraint exists on the category side: more than one Reporting Manager per category is deliberately allowed.

## Organization Chart — `GET /api/v1/users/me/organization-chart`

Backed by `OrganizationService` (`app/rbac/services/organization_service.py`). Builds the full company chain from the top down through the viewer, then continuing down through their own subordinates — never a fixed, static tree. Downward expansion tags each edge `relationship_to_parent`: `"reports_to"` / `"reporting_manager"` / `"assignable"`. Upward expansion stays narrow — only the viewer's real connected Account Manager(s), never a sibling's unrelated branch.

**Note**: `_build_subtree`/`get_subordinate_user_ids` (used to scope permission-override grant authority) are deliberately narrower and untouched by this chart's wider display logic — see [16-known-limitations](../16-known-limitations/functional-limitations.md).

## RBAC-native Audit Logs — `app/rbac/api/v1/audit_logs.py` (prefix `/audit-logs`)

**Do not confuse this table (`audit_logs`, `app.rbac`) with the Ticketing domain's separate `ticket_audit_logs` table** — see [03-business-workflows/audit/audit-workflow.md](../03-business-workflows/audit/audit-workflow.md) for why two systems both use the phrase "audit log."

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/audit-logs` | Create a manual system-level audit log (admin escape hatch — not the real audit-writing path; zero legitimate callers repo-wide) | authenticated + hardcoded `role.name == "Super Admin"` check |
| GET | `/api/v1/audit-logs` | List audit logs (paginated) | `audit:view` |
| GET | `/api/v1/audit-logs/export` | Stream every matching audit log as CSV (unpaginated) | `audit:view` **and** `audit:export` |
| GET | `/api/v1/audit-logs/{id}` | Get one audit log | `audit:view` |
| GET | `/api/v1/audit-logs/user/{user_id}` | All audit logs for one user | `audit:view` |
| DELETE | `/api/v1/audit-logs/{id}` | **Retired outright (Phase 6 / BD-HC3)** — no longer registered on the router; `AuditLogService.delete_log`/`AuditLogRepository.delete` were removed alongside it, since the route was their only caller. Audit rows are append-only by design; a repo-wide search confirmed zero legitimate callers before removal. | n/a |

**Corrected note (was previously stale here): only `create` still uses the hardcoded `role.name == "Super Admin"` check, by deliberate design** — it's an administrative escape hatch, not the system's real audit-writing path, and the "Super Admin" string is intentional there, not an oversight. `list`/`get`/`user`/`export` were moved onto the real `audit:view`/`audit:export` permission system (Phase 6 / BD-HC2 and a later export-permission pass): the prior hardcoded check on `list` had already caused a real bug — a Site Lead holding `audit:view` by default but not literally named "Super Admin" got a 403 the frontend's own permission gate didn't predict. See `docs/AUDIT_LOG_BACKLOG.md` and `docs/04-functional-modules/audit-management.md` for the current state and what (if anything) remains outstanding here.

**Writers of RBAC `audit_logs`** (confirmed, not exhaustive of every mutation in the system): `AuthService` (`auth.login`, `auth.login_failed`, `auth.logout`, `auth.change_password`), `UserService` (`user.create/update/delete/activate/deactivate/role_changed`), `RoleService` (`role.create/update/delete`), `RolePermissionService` (`role.permissions_added/removed`), `PermissionOverrideService`, `PermissionRequestService`. Many other RBAC mutations still leave this table untouched — verify per-action before assuming a row exists.
