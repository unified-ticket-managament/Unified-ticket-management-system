# Users, Roles, Permissions, Categories API

Source: `app/rbac/api/v1/{users,roles,role_permissions,permissions,categories}.py`, all under `/api/v1`. Services: `UserService`, `RoleService`, `RolePermissionService`, `CategoryService` (`app/rbac/services/`).

**Read this alongside [08-security/authorization-rbac.md](../08-security/authorization-rbac.md)**: most of this group's routes do carry an explicit `ensure_has_permission(...)` check (confirmed in this pass) — this domain is **better enforced than the "authorization stops at the frontend" description in some historical docs implies**, though `categories.py` and `permissions.py`'s create/update/delete still have no explicit permission check beyond authentication. Verify current enforcement per-route before assuming either extreme.

## Users — `app/rbac/api/v1/users.py` (prefix `/users`)

| Method | Path | Purpose | Auth / permission |
|---|---|---|---|
| POST | `/api/v1/users` | Create a user | `user:create` |
| GET | `/api/v1/users` | List users (paginated, search, category filter) | `user:view` |
| GET | `/api/v1/users/me/organization-chart` | Org hierarchy chart centered on caller | authenticated only |
| GET | `/api/v1/users/{user_id}` | Get user by id | `user:view` |
| PUT | `/api/v1/users/{user_id}` | Update user | `user:update` |
| DELETE | `/api/v1/users/{user_id}` | Delete user | authenticated only (no explicit permission check confirmed) |
| PATCH | `/api/v1/users/{user_id}/activate` | Activate account | `user:disable` |
| PATCH | `/api/v1/users/{user_id}/deactivate` | Deactivate account | `user:disable` |

**Business rules** (`UserService.create_user`/`update_user`):
- `employee_number` is required and validated for uniqueness for the five internal roles (`DESIGNATION_REQUIRED_ROLE_NAMES`); Client is exempt.
- `manager_id`/`teamlead_id` are validated for role-and-category consistency (`_validate_manager_and_teamlead`) — not just existence.
- Any change to `role_id`/`category_id`/`manager_id`/`teamlead_id`/`is_active` bumps `permission_version` on the affected row, invalidating the RBAC session cache for that user within one TTL window.
- Deactivating/activating and every create/update/delete writes an audit log row (`user.create`/`user.update`/`user.delete`/`user.activate`/`user.deactivate`/`user.role_changed`).

**Side effects**: audit log writes (see above); `permission_version` bump; on category/role change, potentially affects ticket-visibility scoping the next time that user's cache entry is refreshed.

## Roles — `app/rbac/api/v1/roles.py` + `role_permissions.py` (prefix `/roles`)

| Method | Path | Purpose | Auth / permission |
|---|---|---|---|
| POST | `/api/v1/roles` | Create role | `role:create` |
| GET | `/api/v1/roles` | List roles | `role:view` |
| GET | `/api/v1/roles/{role_id}` | Get role | `role:view` |
| GET | `/api/v1/roles/{role_id}/users` | List users holding this role (company-wide) | `role:view` + `user:view` |
| PUT | `/api/v1/roles/{role_id}` | Update role | `role:update` |
| DELETE | `/api/v1/roles/{role_id}` | Delete role | `role:delete` |
| GET | `/api/v1/roles/{role_id}/permissions` | Get a role's permission set | `permission:view` |
| PUT | `/api/v1/roles/{role_id}/permissions` | Replace a role's entire permission set | `permission:update` |

**Business rules**: `PUT .../permissions` (`RolePermissionService.replace_permissions`) diffs the old vs. new set and writes only `role.permissions_added`/`role.permissions_removed` for what actually changed — never a blanket re-log. It also bumps `permission_version` in bulk (one `UPDATE ... WHERE role_id = :id`) for **every** user holding that role — this is the highest-impact single write in the RBAC domain, since it can affect hundreds of active sessions at once.

## Permissions — `app/rbac/api/v1/permissions.py` (prefix `/permissions`)

| Method | Path | Purpose | Auth / permission |
|---|---|---|---|
| POST | `/api/v1/permissions` | Create permission | authenticated only |
| GET | `/api/v1/permissions` | List permissions | `permission:view` |
| GET | `/api/v1/permissions/{id}` | Get permission | `permission:view` |
| PUT | `/api/v1/permissions/{id}` | Update permission | authenticated only |
| DELETE | `/api/v1/permissions/{id}` | Delete permission | authenticated only |

## Categories — `app/rbac/api/v1/categories.py` (prefix `/categories`)

**Categories are now created dynamically at runtime (2026-08-21) — there is no fixed enum backing `category_name` anymore** (see [06-database/database-overview.md](../06-database/database-overview.md)). Create/update/delete/set-members now require the real `category:create` permission (granted to Super Admin/Site Lead by default, and to Account Manager per the 2026-08-21 seed update) — previously these had no explicit permission check beyond authentication.

| Method | Path | Purpose | Auth / permission |
|---|---|---|---|
| POST | `/api/v1/categories` | Create a category, optionally assigning Staff/Team Lead users to it at the same time | `category:create` |
| GET | `/api/v1/categories` | List categories (default page_size 100), each with a computed `assigned_user_count` | authenticated only |
| GET | `/api/v1/categories/{id}` | Get category (with `assigned_user_count`) | authenticated only |
| PUT | `/api/v1/categories/{id}` | Rename a category | `category:create` |
| DELETE | `/api/v1/categories/{id}` | Delete category (rejected if it still has assigned users) | `category:create` |
| GET | `/api/v1/categories/{id}/members` | List every user currently assigned to this category, with their real role name | authenticated only |
| PUT | `/api/v1/categories/{id}/members` | Full-replace this category's Staff/Team Lead membership (adds what's newly listed, removes what's missing) | `category:create` |

**Business rules**: `category_name` is trimmed and duplicate-checked (case-sensitive exact match) server-side before creation/rename. `POST`'s optional `user_ids` reuses the existing `user_categories` many-to-many mechanism (`UserRepository.add_users_to_category`) rather than a second relationship — every id is validated to resolve to a real user first, never trusted blindly from the frontend. `assigned_user_count` is always computed (a batched query across the listed categories, never per-row) and is never a persisted column.

**Note**: There is a second, ticketing-domain `GET /categories` (`app/ticketing/api/category.py`, unprefixed route group) — see [clients-categories-rules.md](clients-categories-rules.md). The two are separate endpoints against the same underlying `categories` table; don't confuse them when integrating.
