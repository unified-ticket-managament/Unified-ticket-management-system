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
| POST | `/api/v1/audit-logs` | Create a manual system-level audit log | authenticated + hardcoded `role.name == "Super Admin"` check |
| GET | `/api/v1/audit-logs` | List audit logs (paginated) | authenticated + hardcoded `role.name == "Super Admin"` check |
| GET | `/api/v1/audit-logs/{id}` | Get one audit log | `audit:view` |
| GET | `/api/v1/audit-logs/user/{user_id}` | All audit logs for one user | `audit:view` |
| DELETE | `/api/v1/audit-logs/{id}` | Delete an audit log | authenticated + hardcoded `role.name == "Super Admin"` check |

**Note the inconsistency, confirmed as-is in code**: the list/create/delete endpoints check a hardcoded role name string rather than the `audit:view`/`audit:export` permission the rest of this domain uses — worth flagging if this area is ever revised, since it means a future role rename ("Super Admin" → something else) would silently break these three routes without an obvious error.

**Writers of RBAC `audit_logs`** (confirmed, not exhaustive of every mutation in the system): `AuthService` (`auth.login`, `auth.login_failed`, `auth.logout`, `auth.change_password`), `UserService` (`user.create/update/delete/activate/deactivate/role_changed`), `RoleService` (`role.create/update/delete`), `RolePermissionService` (`role.permissions_added/removed`), `PermissionOverrideService`, `PermissionRequestService`. Many other RBAC mutations still leave this table untouched — verify per-action before assuming a row exists.
