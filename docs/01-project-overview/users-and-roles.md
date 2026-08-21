# Users and Roles

Six roles exist in `roles` (seeded by `scripts/rbac_seed/seed.py`), ranked in a hierarchy with one deliberate exception:

| Role | Rank | Summary |
|---|---|---|
| **Super Admin** | 5 | All permissions. Unconditional authority everywhere (permission overrides, requests, org visibility). Cannot create a permission request (blocked by design, since it already holds everything). |
| **Site Lead** | 4 | All permissions except `ticket:system_config`/`audit:export`. Company-wide overseer — sits **outside** the reporting-hierarchy tree (`OrganizationService.ROLE_HIERARCHY` excludes it) rather than at its top; unconditional ticket visibility instead of a place in the org chart. |
| **Account Manager** | 3 | Renamed in-place from "Manager" (same `role_id`). Owns a portfolio of Clients. Can transfer tickets to *any* Team Lead company-wide (a deliberately widened capability, independent of real reporting lines — see [04-functional-modules/organization-structure.md](../04-functional-modules/organization-structure.md)). |
| **Team Lead** | 2 | Manages a category's Staff. The default starting point for most ticket escalations. |
| **Staff** | 1 | Front-line agent. Works assigned and pool tickets within their category. |
| **Client** | outside the ladder | External, ticket-submitting party's RBAC-visible representation (renamed in-place from "Viewer" — same `role_id`). Small, fixed permission set (`user:view`, `role:view`, `permission:view`). |

## Role vs. Client (the external party)

Do not confuse the **Client** *role* (an RBAC concept, a small permission set for a client-facing account) with a **Client** *entity* (`clients` table — the external company whose emails become tickets, owned by an Account Manager). They share a name but are different concepts entirely — see [18-glossary](../18-glossary/README.md).

## Reporting Manager — a responsibility, not a role

A **Reporting Manager** is not a seventh role. It's an additional, assignable HR/people-management responsibility layered onto an existing Account Manager for one or more Categories (`reporting_manager_teams` table) — deliberately never granted automatically by holding the Account Manager role. See [04-functional-modules/organization-structure.md](../04-functional-modules/organization-structure.md).

## Capability summary by role (high level — full detail in [08-security/authorization-rbac.md](../08-security/authorization-rbac.md))

| Capability | Super Admin | Site Lead | Account Manager | Team Lead | Staff | Client |
|---|---|---|---|---|---|---|
| Manage users/roles/permissions | Full | Full (minus 2 permissions) | Own subordinates only | — | — | View only |
| View/act on tickets | All | All | Own clients' tickets | Own category | Own assigned + pool | — |
| Close/reopen a ticket unconditionally | Yes | Yes | Only with `ticket:close_ticket` | Only with permission | Only with permission | — |
| Manually escalate | Yes | Yes | Yes (`ticket:escalate`) | Yes | — | — |
| Edit SLA policy targets | Yes | Yes | — | — | — | — |
| Assign Reporting Managers | Yes | Yes | — | — | — | — |

## Where roles are enforced

- **Ticketing domain** (`app.ticketing`): real, server-side role/permission/category/client-ownership checks throughout `access_control.py`.
- **RBAC domain** (`app.rbac`): historically authentication-only on most routes; a 2026-07-14/15 compliance audit added real permission checks to the highest-impact gaps (permission overrides, Users/Roles/Permissions/Audit-Log routes) — see [08-security/authorization-rbac.md](../08-security/authorization-rbac.md) for exactly which routes are and aren't covered today.
