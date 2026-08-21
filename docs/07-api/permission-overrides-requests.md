# Permission Overrides & Permission Requests API

Source: `app/rbac/api/v1/permission_overrides.py`, `permission_requests.py`. Services: `PermissionOverrideService`, `PermissionRequestService`. Full business-rule detail lives in `unified-frontend/CLAUDE.md`'s "Per-user permission overrides" and "Permission requests" sections — this reference summarizes the API surface; see [04-functional-modules/rbac-authorization.md](../04-functional-modules/rbac-authorization.md) for the full workflow.

## Permission Overrides — `app/rbac/api/v1/permission_overrides.py` (prefix `/users`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/users/{user_id}/permission-overrides` | Grant a personal permission override | authenticated; real authorization inside `PermissionOverrideService.grant` |
| GET | `/api/v1/users/{user_id}/permission-overrides` | List a user's overrides (optional `include_revoked`) | authenticated; scoped inside service |
| DELETE | `/api/v1/users/{user_id}/permission-overrides/{override_id}` | Revoke an override | authenticated; scoped inside service |

**Business rules**:
- `grant()` rejects (400) a permission the target's role already includes — "would be redundant."
- Optional `scope_ticket_id` restricts the grant to one ticket only; `NULL` means global.
- Authorization (`ensure_can_manage_overrides`): Super Admin/Site Lead unconditional; Account Manager restricted to their own subordinate tree (`OrganizationService.get_subordinate_user_ids`).
- Every grant/revoke writes an audit log row.
- **Note**: `POST .../permission-overrides` is this route's endpoint that authorization is enforced by; this is one of the very few RBAC-domain checks that was real *before* the 2026-07-14/15 compliance audit — it's the historical exception, not a product of that audit.

## Permission Requests — `app/rbac/api/v1/permission_requests.py` (prefix `/permission-requests`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/permission-requests/eligible-permissions` | Permissions the caller doesn't already effectively hold |
| GET | `/api/v1/permission-requests/eligible-approver-roles` | Which roles could grant a given permission |
| GET | `/api/v1/permission-requests/eligible-approver-users` | Real, specific people the caller may address a request to |
| GET | `/api/v1/permission-requests/scope/staff-options` | Teammates (same Team Lead) — for a ticket-scoped request |
| GET | `/api/v1/permission-requests/scope/ticket-options?staff_id=` | A teammate's assigned tickets — for a ticket-scoped request |
| POST | `/api/v1/permission-requests` | Create a request, addressed to one selected approver |
| GET | `/api/v1/permission-requests/mine` | Caller's own requests, every status |
| GET | `/api/v1/permission-requests/pending-for-review` | Requests addressed to the caller, still pending |
| GET | `/api/v1/permission-requests/history` | Decided requests in the caller's oversight scope |
| POST | `/api/v1/permission-requests/{id}/approve` | Approve (only the exact selected approver may call this) |
| POST | `/api/v1/permission-requests/{id}/reject` | Reject (only the exact selected approver) |
| POST | `/api/v1/permission-requests/{id}/revoke` | Revoke a previously-approved request (original approver or Super Admin only) |

**Key business rules**:
- A request is addressed to **one specific person** (`selected_approver_id`), never a role — `create_request` re-derives the eligible-candidate set server-side and rejects any `selected_approver_id` outside it (400), so a client can't submit an approver it wasn't actually shown.
- `approve()`/`reject()` require `current_user.user_id == selected_approver_id` exactly — **no Super Admin/Site Lead bypass**, confirmed live during the 2026-07-14/15 audit.
- Super Admin cannot create a request at all (400) — defense-in-depth, since Super Admin already holds every permission by default.
- Approving calls `PermissionOverrideService.grant()` directly and stores the resulting `override_id` back on the request row — exactly one code path ever creates a `UserPermissionOverride`.
- `revoke()` requires the request to currently be `APPROVED`; only the original `reviewed_by` approver or Super Admin may call it. The row is never deleted — only `status` transitions (`PENDING → APPROVED/REJECTED`, `APPROVED → REVOKED`).
- `history` is a broader oversight view than "pending for review": Super Admin/Site Lead see everything decided; Account Manager sees their own reports' decisions.
- Duplicate-request prevention keys off `(requester_id, permission_id, COALESCE(scope_ticket_id, sentinel))` — two *different* ticket-scoped requests for the same permission don't collide; two global ones do.

**Side effects**: `notify()` is called for exactly the selected approver (create), and for the requester (approve/reject/revoke) — never a role-wide fan-out. Audit logging captures `previous_status`/`new_status` pairs on every transition.
