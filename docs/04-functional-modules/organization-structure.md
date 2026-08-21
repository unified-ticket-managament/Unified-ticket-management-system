# Organization Structure Module

## Purpose
Model three genuinely independent business relationships that a flat RBAC role ladder can't express on its own: real reporting lines, an additional Reporting-Manager HR responsibility, and a company-wide ticket-assignment capability.

## Responsibilities
- Reporting Manager assignment (Account Manager ↔ Category, many-to-many).
- Dynamic, per-viewer organization chart (full company chain from the top down through the viewer, then down through their own subordinates).
- Widened ticket-assignment scope (Account Manager can transfer to any Team Lead company-wide; a Staff target is unconditionally category-scoped).
- Manager/category consistency validation on user create/update.

## Main Components
- `app/rbac/services/{organization_service,reporting_manager_service}.py`
- `app/rbac/repositories/reporting_manager_repository.py`
- `app/rbac/models/reporting_manager_team.py`
- `app/ticketing/services/assignment_service.py`

## Inputs
User role/category/manager_id/teamlead_id assignments; Reporting Manager assign/revoke actions.

## Outputs
`GET /users/me/organization-chart`'s per-viewer tree; `AssignmentService.get_assignable_groups`'s candidate lists.

## Business Rules
- **Three relationships, never collapsed into one**: (1) real reporting line (`manager_id`/`teamlead_id`), (2) Reporting Manager mapping (`reporting_manager_teams`, HR responsibility, never a role), (3) unrestricted ticket-assignment capability (Account Manager → any Team Lead company-wide).
- A category can have more than one Reporting Manager — no uniqueness constraint on the category side, per an explicit "should be dynamic, not hardcoded" requirement.
- `_build_subtree`/`get_subordinate_user_ids` (used to scope permission-override grant authority) are **deliberately narrower** than the org chart's display logic and untouched by this module's widening — neither a Reporting Manager assignment nor the ticket-assignment relationship should ever widen who an Account Manager can grant/revoke permissions for.
- `manager_id`/`teamlead_id` are validated for role-and-category consistency on create/update, not just existence — a Staff member can never be assigned a Team Lead from a different category.

## Dependencies
`UserRepository`, `RoleRepository`, `CategoryRepository`.

## Database Entities
`reporting_manager_teams`, `users.manager_id`/`.teamlead_id`/`.reporting_manager_id`/`.category_id`.

## APIs
[07-api/organization-audit.md](../07-api/organization-audit.md).

## Important Classes/Services
`OrganizationService`, `ReportingManagerService`, `AssignmentService`.

## External Integrations
None.

## Known Limitations
- The actual HR action surface a Reporting Manager would need (Approve/Reject Leave, View Attendance/Performance/Timesheets, Conduct Reviews, Team KPIs) is **entirely unbuilt** — this module is data-model/permission/org-chart plumbing only.
- No availability/shift-presence tracking exists to inform any future workload-aware assignment decision.

## Categories are now dynamically managed (added 2026-08-21)

The work-specialization Categories that scope Staff/Team Lead visibility (see [06-database/database-overview.md](../06-database/database-overview.md)) are no longer a fixed, migration-gated list — a Super Admin/Site Lead/Account Manager holding the new `category:create` permission can create a category at runtime (optionally assigning Staff/Team Lead users to it immediately), and a new **Category Management** admin page (`/categories` in `unified-frontend`) supports full CRUD plus a dedicated **Category Members** editor (`GET/PUT /categories/{id}/members`) for adding/removing Team Lead/Staff membership after the fact — reusing the pre-existing `user_categories` many-to-many table, not a new relationship. See [07-api/users-roles-permissions.md](../07-api/users-roles-permissions.md).

## Related workflows
[03-business-workflows/ticket/ticket-assignment.md](../03-business-workflows/ticket/ticket-assignment.md) (the widened Account-Manager-to-any-Team-Lead rule this module introduces).
