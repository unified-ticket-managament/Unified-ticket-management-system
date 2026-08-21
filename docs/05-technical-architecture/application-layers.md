# Application Layers

Both `app/rbac/` and `app/ticketing/` follow the same layering:

```
API (routes)  →  Service (business logic + authorization)  →  Repository (data access)  →  Model (SQLAlchemy)
```

## Where each concern lives

| Concern | Layer | Notes |
|---|---|---|
| Request/response shape validation | Pydantic schemas (`schemas/`), enforced at the route boundary | FastAPI validates automatically before the route body runs |
| Authentication | `app/dependencies/auth.py`, shared by both domains | `get_current_user`/`get_current_agent`/`get_current_user_sse` |
| Authorization | Mostly in **services**, not routes — e.g. `ensure_has_permission`, `ensure_agent_can_view_ticket`, `ensure_can_manage_overrides` | See [08-security/authorization-rbac.md](../08-security/authorization-rbac.md) for exactly how uneven this is across the two domains |
| Business logic | Services (`services/*.py`) | This is where SLA math, escalation rules, permission resolution, etc. all live |
| Data access | Repositories (`repositories/*.py`) | Raw SQLAlchemy queries; no business logic |
| Persistence | Models (`models/*.py`) | Plain SQLAlchemy ORM classes |
| Scheduled/background work | `app/core/sla_scheduler.py`, `graph_mail_poll_scheduler.py`, `graph_subscription_scheduler.py` | Wired into the FastAPI `lifespan` hook, not a separate process |
| Cross-cutting notification | `app/notifications/service.py` | Called *from* services in both domains, never bypassed |
| Configuration | `app/core/config.py`'s `Settings`, `@lru_cache`d | The one place every env var is declared/typed |

## A concrete example: creating a ticket

1. **API** (`app/ticketing/api/ticket.py`): `POST /tickets/from-interaction` validates the request body (`TicketFromInteractionRequest` schema) and calls `get_current_agent`.
2. **Service** (`app/ticketing/services/ticket_service.py`): `TicketService.create_ticket` validates the client association, initializes state, generates the ticket number, and calls into `SLAService` to start the Resolution clock.
3. **Repository** (`app/ticketing/repositories/ticket_repository.py`): `TicketRepository.create` performs the actual `INSERT`.
4. **Model** (`app/ticketing/models/ticket.py`): the `Ticket` SQLAlchemy class defines the table shape the repository writes against.

## A deliberate deviation: business logic distributed across many small services, not one "God service"

`app/ticketing/services/` has 30 files — `SLAService`, `EscalationService`, `EscalationHandlingSlaService`, `InteractionService`, `AssignmentService`, `AttachmentService`, etc. are each scoped to one concern, calling into each other explicitly (e.g. `EscalationService` calls `SLAService.reshift_resolution_clock_for_priority_change` via a deferred import to avoid a circular dependency) rather than one monolithic ticket service owning everything. See [15-architecture-decisions/ADR-003-ticket-interaction-separation.md](../15-architecture-decisions/ADR-003-ticket-interaction-separation.md).

## Where the layering is NOT followed strictly

- RBAC's own routes historically checked authentication only, with authorization logic partially absent rather than simply "in the service" — see [08-security/authorization-rbac.md](../08-security/authorization-rbac.md) for exactly which routes now have a real service-layer check versus which still don't.
- A few RBAC-domain audit checks are hardcoded role-name string comparisons directly at the route/service boundary (`current_user.role.name == "Super Admin"`) rather than a permission-based check — a known, confirmed inconsistency (see [07-api/organization-audit.md](../07-api/organization-audit.md)).
