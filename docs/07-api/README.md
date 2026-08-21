# API Reference

The backend is one FastAPI app (`unified-backend/app/main.py`) serving two domains from one process:

- **RBAC API** — mounted at prefix `/api/v1` (`app/rbac/api/v1/api_router.py`)
- **Ticketing API** — mounted unprefixed, each router carrying its own path prefix (`app/ticketing/api/*.py`)
- **Notifications API** — mounted unprefixed at `/notifications` (`app/notifications/routes.py`)

Interactive documentation is always available against a running backend at `/docs` (Swagger UI) and `/redoc` — treat those as the live, always-current source; this reference explains *why* each group of endpoints exists and what business rules sit behind them, which OpenAPI alone doesn't capture.

## Authentication model (summary — full detail in [08-security](../08-security/README.md))

Almost every endpoint requires a Bearer JWT, via one of these FastAPI dependencies:

| Dependency | Meaning |
|---|---|
| `get_current_active_user` (RBAC domain) | Authenticated, active user — no role/permission check |
| `get_current_user` (Ticketing domain) | Authenticated, active user — read-oriented endpoints |
| `get_current_agent` (Ticketing domain) | Authenticated, active **agent-role** user (Staff/Team Lead/Account Manager/Site Lead/Super Admin) — write-oriented endpoints |
| `get_current_user_sse` | Same identity check as `get_current_user`, but reads the token from a `?token=` query parameter (browsers' `EventSource` can't set headers) and opens its own short-lived DB session instead of holding a request-scoped one for the connection's whole lifetime |
| `ensure_has_permission(...)` / `has_permission(...)` | An additional, real permission-claim check layered on top of one of the above — only present on specific endpoints (noted per-endpoint below) |
| *(none)* | Public — login/refresh, health check, docs, and the two inbound-mail webhook receivers (secured by transport-level integrity checks instead, not a bearer token) |

## Endpoint groups

| Area | Document | Router source |
|---|---|---|
| Authentication | [auth.md](auth.md) | `app/rbac/api/v1/auth.py` |
| Users, Roles, Permissions | [users-roles-permissions.md](users-roles-permissions.md) | `app/rbac/api/v1/{users,roles,role_permissions,permissions,categories}.py` |
| Permission Overrides & Requests | [permission-overrides-requests.md](permission-overrides-requests.md) | `app/rbac/api/v1/{permission_overrides,permission_requests}.py` |
| Organization & Audit (RBAC) | [organization-audit.md](organization-audit.md) | `app/rbac/api/v1/{reporting_managers,audit_logs}.py`, org-chart endpoint in `users.py` |
| Tickets | [tickets.md](tickets.md) | `app/ticketing/api/ticket.py` |
| Inbox / Mail | [inbox-mail.md](inbox-mail.md) | `app/ticketing/api/inbox.py` |
| SLA & Escalation | [sla-escalation.md](sla-escalation.md) | `app/ticketing/api/{sla.py,sla_internal.py}` |
| Interactions, Agents, Attachments | [interactions-agents-attachments.md](interactions-agents-attachments.md) | `app/ticketing/api/{interaction,agent,attachment}.py` |
| Clients, Categories, Folders, Rules | [clients-categories-rules.md](clients-categories-rules.md) | `app/ticketing/api/{client,category,mail_folder,rule}.py` |
| Mail integration (Graph/N8N) | [mail-integration.md](mail-integration.md) | `app/ticketing/api/{mail_integration,email}.py` |
| Notifications | [notifications.md](notifications.md) | `app/notifications/routes.py` |

## Conventions used across every endpoint doc

- **Path/Method** as actually declared in the router (`@router.get/post/...` + the router's own `prefix=`) — not inferred.
- **Auth** — the dependency chain above, plus any additional permission check enforced *inside* the service layer (many endpoints only check authentication at the route level; the real authorization check lives in the service — this is called out explicitly per endpoint since it's a real architectural pattern in this codebase, not an oversight to "fix").
- **Side Effects** — DB writes, notifications fired, audit events logged, external calls made — beyond just "creates/reads a row."
- Endpoints that only check authentication, with no deeper permission gate at all, are marked **"no explicit permission check"** — this is accurate as of this documentation pass for the RBAC domain in particular (see [08-security/authorization-rbac.md](../08-security/authorization-rbac.md)), not a mistake in this reference.
