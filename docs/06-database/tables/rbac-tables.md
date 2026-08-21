# RBAC Tables

## `users` (`shared_models/shared_models/models/user.py`)

The single source of truth for every person (and Client-role account) in the system — includes `TimestampMixin` (`created_at`/`updated_at`).

| Column | Type | Null? | Default | Business meaning |
|---|---|---|---|---|
| user_id | UUID | NOT NULL | uuid4 | Primary key, never reused, never shown to end users in place of Employee ID |
| name | String(100) | NOT NULL | | |
| email | String(255) | NOT NULL | | UNIQUE, indexed — the login identity |
| password_hash | String(255) | NOT NULL | | bcrypt hash |
| role_id | UUID | NOT NULL | | FK→roles — drives the whole RBAC model |
| manager_id | UUID | NULL | | FK→users (self) — real reporting line to an Account Manager |
| teamlead_id | UUID | NULL | | FK→users (self) — real reporting line to a Team Lead |
| reporting_manager_id | UUID | NULL | | FK→users (self) — Org-Chart-only, independent of manager/teamlead (see [organization-structure.md](../../04-functional-modules/organization-structure.md)) |
| category_id | UUID | NULL | | FK→categories — legacy single-category assignment |
| is_active | Boolean | NOT NULL | True | Deactivation gate — also bumps `permission_version` |
| is_on_leave | Boolean | NOT NULL | false | Display-only — no availability-aware routing reads this yet |
| permission_version | Integer | NOT NULL | 1 | RBAC session-cache invalidation key — bumped on any auth-relevant change |
| date_of_birth | Date | NULL | | Profile field |
| alternate_email | String(255) | NULL | | Profile field |
| phone_number | String(30) | NULL | | Profile field |
| office_location | String(255) | NULL | | Profile field |
| department | String(100) | NULL | | Display-only — deliberately independent of `category_id`, no authorization weight |
| team | String(100) | NULL | | Display-only, never edited via any UI surface |
| designation | String(150) | NULL | | Display-only job title |
| employee_number | String(20) | NULL | | UNIQUE — the real, human-assigned Employee ID, required for internal roles at creation |
| language | String(10) | NULL | "en" | |
| date_format | String(20) | NULL | "MM/DD/YYYY" | |
| time_format | String(10) | NULL | "12h" | |
| time_zone | String(50) | NULL | | |
| default_dashboard | String(50) | NULL | "Dashboard" | |

## `roles`

`role_id` (UUID PK), `name` (String(100), UNIQUE, indexed, NOT NULL) — six seeded rows: Super Admin, Site Lead, Account Manager, Team Lead, Staff, Client.

## `categories`

`category_id` (UUID PK), `category_name` (**as of 2026-08-21, a plain `String(150)`, UNIQUE, indexed, NOT NULL** — previously a native Postgres enum `category_name_enum` fixed to 8 members; converted by `alembic_rbac`'s `a4c6e8b0d2f5_category_name_enum_to_varchar` migration, which dropped the Postgres type and deleted the backing Python `CategoryName` enum entirely). Department/queue grouping that scopes ticket visibility — distinct from `users.department` (display-only, no relation).

Categories are now created **dynamically at runtime** through `POST /categories` (`category:create` permission — granted to Super Admin/Site Lead by default, and to Account Manager per the 2026-08-21 seed update) — no code change or migration is needed per new category, a deliberate reversal of the original fixed-enum design. `CategoryResponse.assigned_user_count` is a computed, non-persisted field (batch-queried by `CategoryService`, never a real column) showing how many users hold that category via `user_categories`.

**Category Members**: `GET/PUT /categories/{id}/members` manage a category's Staff/Team Lead membership directly (full-replace semantics on `PUT`, diffing submitted `user_ids` against the current `user_categories` rows) — this reuses the same M2M table `user_categories` already documented above, not a new relationship. See [07-api/users-roles-permissions.md](../../07-api/users-roles-permissions.md).

## `user_categories` (plain join table, no ORM class)

`user_id` (FK→users CASCADE, PK), `category_id` (FK→categories CASCADE, PK, indexed), `assigned_by` (FK→users SET NULL), `assigned_at` (DateTime tz, NOT NULL) — the newer multi-category membership model, coexisting with the legacy scalar `users.category_id`.

## `permissions`

`permission_id` (UUID PK), `permission_name` (String(100), UNIQUE, indexed, NOT NULL — e.g. `ticket:close_ticket`), `description` (Text, null), `created_at`.

## `role_permissions`

Composite PK `(role_id, permission_id)`, both CASCADE FKs — the default permission bundle per role.

## `audit_logs` (RBAC-native — distinct from ticketing's `ticket_audit_logs`)

`audit_log_id` (PK), `user_id` (FK→users SET NULL, indexed), `action` (String(100), indexed — e.g. `auth.login`, `user.update`), `entity_type` (String(100), indexed), `entity_id` (String(100), null), `old_value`/`new_value` (Text), `ip_address` (String(50)), `user_agent` (String(500)), `timestamp` (indexed).

## `user_permission_overrides`

`override_id` (PK), `user_id` (FK CASCADE, indexed), `permission_id` (FK CASCADE), `granted_by`/`revoked_by` (FK SET NULL), `reason`, `granted_at`, `expires_at` (null = permanent), `revoked_at`, **`scope_ticket_id`** (plain UUID, no FK — deliberately, see [relationships.md](../relationships.md)). Partial UNIQUE index on `(user_id, permission_id, COALESCE(scope_ticket_id, sentinel))` `WHERE revoked_at IS NULL`.

## `permission_requests`

`request_id` (PK), `requester_id` (FK, indexed), `permission_id` (FK), `requested_role` (String(100) — immutable display snapshot only, never an authorization check), `selected_approver_id` (FK→users — the real authorization target), `reason` (Text), `scope_ticket_id` (plain UUID, no FK), `status` (String(20), default PENDING, indexed — plain string, not a DB enum), `reviewed_by`/`reviewed_at`/`review_comment`, `expires_at`, `granted_override_id` (FK→user_permission_overrides SET NULL), `revoked_by`/`revoked_at`/`revoke_reason`, `created_at`. Partial UNIQUE index on `(requester_id, permission_id, COALESCE(scope_ticket_id, sentinel))` `WHERE status='PENDING'`.

## `reporting_manager_teams`

`id` (PK), `account_manager_id` (FK→users CASCADE, indexed), `category_id` (FK→categories CASCADE, indexed), `assigned_by` (FK→users SET NULL), `assigned_at`. `UNIQUE(account_manager_id, category_id)` — but a category can still have multiple Reporting Managers (no per-category uniqueness), and one Account Manager can hold this responsibility for multiple categories.
