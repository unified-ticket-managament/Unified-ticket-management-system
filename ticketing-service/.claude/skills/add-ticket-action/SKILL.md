---
name: add-ticket-action
description: Scaffold a new ticket-mutating action (like status change, resolve, transfer) end-to-end across backend and frontend, following this repo's established pattern. Use when asked to add a new action/button that changes a ticket and must show up on the timeline, audit log, and UI (e.g. "add an Escalate action", "add a Reopen button", "add a Merge Tickets action").
---

# Add a ticket-mutating action

This repo has one repeated recipe for any action that changes a ticket and must be
traceable (timeline + audit trail + UI). Follow it exactly rather than inventing a new
shape — copy the closest existing action (`change_status` / `transfer_agent` /
`claim_ticket` in `backend/app/services/interaction_service.py` are the best templates)
and adapt.

Read `CLAUDE.md` first for the two-log distinction (Interaction = business timeline,
AuditLog = immutable compliance trail), the real-JWT auth model (no more `agent_name`
query param), and the Postgres-enum migration gotcha before touching audit event types —
use the **add-postgres-enum-value** skill if this action needs a new `AuditEventType`
member.

## Backend steps

1. **Audit event type** — if this action needs a new `AuditEventType` value, add it to
   `backend/app/enums/audit_enums.py`, then run the **add-postgres-enum-value** skill to
   generate the matching Alembic migration (`ALTER TYPE audit_event_type_enum ADD VALUE`).
   Skip this if an existing event type fits.
2. **Request schema** — add a `<Verb>Request` Pydantic model to
   `backend/app/schemas/ticket_action.py` (see `ResolveTicketRequest`, `StatusChangeRequest`).
   Keep it minimal — most actions need zero or one field.
3. **Service method** — add a method to `InteractionService` in
   `backend/app/services/interaction_service.py`, right next to the most similar existing
   method (`change_status`/`change_priority`/`transfer_agent`/`claim_ticket` are the best
   templates), following this exact shape:
   - `ticket = await self._get_ticket_or_404(ticket_id)`
   - capture any "before" state you'll need for the interaction/audit payload
   - guard against invalid transitions with `HTTPException(400, "...")` if applicable
     (see `ensure_ticket_not_closed` / claim's already-claimed guard)
   - `actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)`
     — synchronous, takes the authenticated `current_user` directly (there is no
     `agent_name` string to resolve; auth is real JWT, not a query param — see CLAUDE.md)
   - mutate the ticket via `self.ticket_repository.update(ticket, TicketUpdate(...))`
   - `interaction = await self._create_ticket_interaction(ticket_id=..., interaction_type="<NEW_TYPE>", direction=InteractionDirection.INTERNAL, payload={...}, performed_by=actor_id)`
     — `interaction_type` is a free string, no migration needed for a new one; only pass
     `parent_interaction_id` if this action is itself a reply/follow-up in the client email
     thread (see CLAUDE.md's threading note) — everything else leaves it `None`
   - `await AuditLogService.log_event(self.ticket_repository.db, entity_type=AuditEntityType.TICKET, entity_id=ticket_id, event_type=..., actor_id=actor_id, actor_name=actor_name, actor_role=actor_role, old_values={...}, new_values={...})`
   - `return TicketActionResponse(interaction_id=interaction.interaction_id, ticket_id=ticket_id, message="...", created_at=interaction.created_at)`
4. **Route** — add `POST /tickets/{ticket_id}/<verb>` to `backend/app/api/ticket.py`,
   wired identically to the `/status` or `/transfer` route: same three repositories, same
   `InteractionService` construction, `current_user: User = Depends(get_current_agent)` —
   not a query param.

## Frontend steps

1. **Types** (`frontend/src/types/index.ts`) — add the request interface, and if you
   added an `AuditEventType` value, add it to that union too.
2. **API wrapper** (`frontend/src/api/interaction.ts`) — thin POST wrapper matching
   `changeTicketStatus`/`changeTicketPriority`. Mirror it into the RBAC-embedded copy's
   `api/interaction.ts` too (see CLAUDE.md's dual-frontend rule).
3. **UI** (`frontend/src/components/ticket/TicketActions.tsx`) — add an `ActionTile`
   (pick a `Tone`/icon that isn't already overloaded) wired through `useApiAction` with a
   `successMessage`, opening a `Modal` if the action needs input, then calling
   `onActionComplete()` on success so the timeline/audit panel refetch.
4. **Timeline rendering** (`frontend/src/lib/interactionMeta.ts`) — add the new
   `interaction_type` to `TYPE_META` (icon/label/tone) and a `summarize()` case, or it
   falls back to a raw JSON dump on the timeline.
5. **Audit rendering** (`frontend/src/lib/auditLogMeta.ts`) — add the new
   `AuditEventType` to `EVENT_META`, or it falls back to a generic bullet.
6. If the action changes a field worth surfacing on the ticket ("related fields"),
   add a row to `frontend/src/components/ticket/TicketDetails.tsx`.

## Verification

- Confirm the new route appears with correct schemas via the OpenAPI spec
  (`GET /openapi.json` while the backend is running, or `TestClient(app).get("/openapi.json")`
  in a throwaway script) — cheaper than a live DB round-trip for catching wiring mistakes.
- If a new Postgres enum value was added, confirm the migration is head
  (`alembic history`) and applied (`alembic upgrade head`) before exercising the action —
  otherwise it 500s with `InvalidTextRepresentationError`.
- Exercise the action from the UI (or Swagger `/docs`) and confirm it shows up in both
  the ticket Timeline and the Audit Trail panel, not just one.
