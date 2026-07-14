---
name: add-ticket-action
description: Scaffold a new ticket-mutating action (like status change, resolve, transfer) end-to-end across backend and frontend, following this repo's established pattern. Use when asked to add a new action/button that changes a ticket and must show up on the timeline, audit log, and UI (e.g. "add an Escalate action", "add a Reopen button", "add a Merge Tickets action").
---

# Add a ticket-mutating action

**Path note**: this repo's own `backend/` is now an empty shell — `rbac-service/backend` and
`ticketing-service/backend` were merged into one process, `unified-backend/` (sibling
directory at the monorepo root). Every `backend/app/...` path in this skill means
`unified-backend/app/ticketing/...` in practice; run backend commands from `unified-backend/`,
not from here. See the root `CLAUDE.md`'s "Backend unification" section.

This repo has one repeated recipe for any action that changes a **ticket** and must be
traceable (timeline + audit trail + UI). Follow it exactly rather than inventing a new
shape — copy the closest existing action (`change_status` / `change_priority` /
`transfer_agent` / `claim_ticket` in `app/services/interaction_service.py` are the
best templates) and adapt.

**If the action instead applies to a pending, pre-ticket `Interaction`** (the shared inbox
pool — e.g. "Assign to me"/claim, "Informational/Archive") — this is a related but distinct
pattern: there's no `Ticket` row yet, so it doesn't go through `TicketRepository`/
`_create_ticket_interaction` at all. Copy `InteractionService.claim_interaction` /
`archive_interaction` instead, which mutate the `Interaction` row directly via a matching
atomic-guard method on `InteractionRepository` (`claim`/`archive`, guarding on
`ticket_id IS NULL AND status == PENDING` plus whatever else the guard needs — `claim` also
checks `claimed_by IS NULL`), mirroring `TicketRepository.claim`'s race-guard shape but keyed
on the Interaction's own columns instead of `Ticket.agent_id`. Access is checked via
`InteractionService._ensure_can_act_on_pending_interaction` (own-client-scope-or-supervisor),
not `ensure_agent_can_view_ticket`. The rest of this skill (below) is written for the
ticket-level case; adapt step 3 accordingly for a pending-interaction action.

**Check whether the new action should also touch an SLA clock** — a cross-cutting concern
layered on top of whichever pattern above applies, not a fourth pattern of its own. If the
action is the *first agent reply* on a ticket, call `SLAService.complete_first_response_clock`
after the interaction/audit-log writes (see `add_reply`/`add_interaction_reply` for the
pattern — guard with `if self.sla_service is not None:`, since it's an optional constructor
dependency not every call site wires in). If the action changes `current_status` to/from
`WAITING_FOR_CLIENT`, or to `CLOSED`, call `SLAService.pause_resolution_clock`/
`resume_resolution_clock`/`complete_resolution_clock` respectively (see `change_status`). If
it changes `current_priority`, call `reshift_resolution_clock_for_priority_change` (see
`change_priority`). If it promotes a pending email into a ticket or attaches one to an
existing ticket, see `InboxTicketService`'s own two methods for `start_resolution_clock`/
`create_or_resume_resolution_clock`. See root `CLAUDE.md`'s "SLA & Escalation" section for
the full clock lifecycle before adding a new touch point — and never let a new action call
into `EscalationService` directly for anything other than reading state; the internal
escalation workflow is a *consumer* of Resolution SLA breach events (via the sweep), not
something ticket actions mutate directly.

**Three further variants exist for shapes that don't fit either pattern above** — see
`CLAUDE.md` for the full detail, summarized here:
- **A thread-scoped, upsertable action** (Drafts): if the action should have "at most one
  active row per thread per agent, overwritten on repeat calls" semantics rather than
  "create a new row every time", look at `InteractionService.save_draft`/`send_draft`/
  `discard_draft` and `_resolve_pending_thread_root` — the shared root-resolution helper
  that lets a caller pass any id within the thread, not just the root's.
- **A symmetric self-referential relation** (Related Tickets): if the action links two
  existing rows of the same type together (not "mutate one row"), look at
  `TicketRelationRepository`/`TicketService.add_related_ticket` — write **both** directions
  at creation so reads never need an `OR`-across-two-columns query, and check visibility
  (`ensure_agent_can_view_ticket`) on *both* sides before linking, not just the one the
  route was called on.
- **A request/review workflow** (Edit Access requests): if the action is really "ask someone
  else to let you do X, they approve or reject" rather than a direct mutation, look at
  `EditAccessService` (`request_access`/`approve`/`reject`/`list_for_ticket`) and
  `TicketEditAccessRequestRepository` — a dedicated status-tracked table (`PENDING`/
  `APPROVED`/`REJECTED`, partial-unique-indexed so only one open request exists per
  requester at a time) rather than an `Interaction`/`AuditLog` row alone, since the request
  itself has a lifecycle to track, not just a point-in-time event. Both the request and
  every review decision still get an `Interaction` + `AuditLog` row each, on top of the
  dedicated table — see the next bullet on combining this with permission-based checks.

Read `CLAUDE.md` first for the two-log distinction (Interaction = business timeline,
AuditLog = immutable compliance trail), the real-JWT auth model (no more `agent_name`
query param), the `OWNED_TABLES` gotcha (a new model's table must be added there before
`alembic revision --autogenerate` will pick it up), and the Postgres-enum migration gotcha
before touching audit event types — use the **add-postgres-enum-value** skill if this
action needs a new `AuditEventType` member.

## Backend steps

1. **Audit event type** — if this action needs a new `AuditEventType` value, add it to
   `backend/app/enums/audit_enums.py`, then run the **add-postgres-enum-value** skill to
   generate the matching Alembic migration (`ALTER TYPE audit_event_type_enum ADD VALUE`).
   Skip this if an existing event type fits. `INTERACTION_CLAIMED`/`INTERACTION_ARCHIVED`
   are recent examples of adding two new values in one migration file — see
   `backend/alembic/versions/9b2c4d6e8f0a_add_interaction_claimed_and_archived_audit_event_types.py`.
2. **Request schema** — add a `<Verb>Request` Pydantic model to
   `backend/app/schemas/ticket_action.py` (see `TransferAgentRequest`, `StatusChangeRequest`).
   Keep it minimal — most actions need zero or one field.
3. **Service method** — add a method to `InteractionService` in
   `backend/app/services/interaction_service.py`, right next to the most similar existing
   method (`change_status`/`change_priority`/`transfer_agent`/`claim_ticket` are the best
   templates), following this exact shape:
   - `ticket = await self._get_ticket_or_404(ticket_id)`
   - `ensure_agent_can_view_ticket(ticket, current_user)` (from `access_control.py`) if the
     action should be visibility-restricted — this is the category/ownership gate.
   - capture any "before" state you'll need for the interaction/audit payload
   - guard against invalid transitions with `HTTPException(400, "...")` if applicable (see
     `ensure_ticket_not_closed`, or `claim_ticket`'s already-claimed guard)
   - if the action should be restricted to *specific roles* rather than just visibility
     (a real authorization rule, not a scoping rule), you have two composable options, not
     mutually exclusive:
     - **Role-name check**: see `ensure_can_reassign_ticket` for the base pattern — a small
       helper in `access_control.py` that 403s unless `current_user.role.name in
       SUPERVISOR_ROLE_NAMES` (or whatever role set applies), called right after the
       closed/view checks. `transfer_agent` uses this to block Staff from reassigning a
       ticket to a *different* named agent, while deliberately **not** applying it to
       `claim_ticket` (self-pickup from the shared pool stays open to every agent role) —
       know which of these two your new action actually is before copying either.
     - **Permission check** (`access_control.ensure_has_permission(current_user,
       "ticket:<name>")`): reads the `permissions` claim RBAC embeds in the JWT — use this
       when the restriction should be overridable per-person (via an rbac-service personal
       permission override) rather than fixed to a role set. `change_priority` uses this
       alone; `ensure_can_reassign_ticket` composes both — role check first, permission
       check as the fallback for anyone the role check didn't already clear — so a specific
       Staff member can be granted the capability without touching `SUPERVISOR_ROLE_NAMES`
       at all. `ensure_can_close_ticket`/`ensure_can_reopen_ticket`/`ensure_can_override_sla`
       are further examples of this composed shape, each with their own narrower bypass set
       (`CLOSE_REOPEN_BYPASS_ROLE_NAMES`/`GLOBAL_INBOX_ROLE_NAMES`, not the wider
       `SUPERVISOR_ROLE_NAMES`) — check the RBAC permission-matrix doc's own Full/Override
       column for the role you're bypassing before reaching for `SUPERVISOR_ROLE_NAMES` by
       default; a 2026-07-14/15 audit found several of these had bypassed too widely (Team
       Lead unconditionally, where the doc marks it Override-only) — see `CLAUDE.md`'s
       "Permission-based enforcement" section for the full list of real call sites this now
       has. See that same section before adding a new `ticket:*` permission name — it must
       also exist in `unified-backend/scripts/rbac_seed/seed.py`'s
       `DEFAULT_PERMISSIONS`/`DEFAULT_ROLES` or no one will ever hold it, and if a mutating
       action reaches a `Ticket` row, also check whether `ensure_account_manager_owns_ticket_client`
       needs calling alongside — several mutating actions had a permission check but no
       Account-Manager-client-boundary check until that same audit. If the new permission
       should be grantable scoped to one specific ticket (not just a blanket role/override
       grant), see `ticket:editother_ticket`'s `scope_ticket_id` pattern in
       `unified-frontend/CLAUDE.md`'s "Per-user permission overrides" section rather than
       inventing a new scoping mechanism.
   - `actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)`
     — synchronous, no DB lookup; `current_user` is the already-verified `User` passed in
     from the route's `Depends(get_current_agent)`, not a name string
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
   not a query param. Use `Depends(get_current_user)` instead of `get_current_agent` only if
   the route should also be reachable by Viewer (read-only routes only — see CLAUDE.md's
   access-control section).

## Frontend steps

This frontend has a second, embedded copy at
`../unified-frontend/src/ticket-workspace/` (formerly `rbac-service/frontend/src/ticket-workspace/`
— mounted inside the shell's Next.js app, see that repo's CLAUDE.md). It is **not** kept in sync automatically. Do the steps
below in this app first, verify the action end-to-end here, then decide whether the
same change needs porting into the embedded copy (same relative paths, but under
`ticket-workspace/` and importing via the `@tw/*` alias instead of `@/*`).

1. **Types** (`frontend/src/types/index.ts`) — add the request interface, and if you
   added an `AuditEventType` value, add it to that union too (and mirror both into the
   embedded copy's `types/index.ts`).
2. **API wrapper** (`frontend/src/api/interaction.ts` or `api/ticket.ts`, matching whichever
   resource the route lives under) — thin POST wrapper matching
   `changeTicketStatus`/`transferTicketAgent`. Identity comes from the bearer token attached
   by `api/client.ts`'s request interceptor — never add an `agentName`/`agent_name` param.
   Mirror it into the RBAC-embedded copy's equivalent `api/*.ts` too (see CLAUDE.md's
   dual-frontend rule).
3. **UI** (`frontend/src/components/ticket/TicketActions.tsx`) — add an `ActionTile`
   (pick a `Tone`/icon that isn't already overloaded) wired through `useApiAction` with a
   `successMessage`, opening a `Modal` if the action needs input, then calling
   `onActionComplete()` on success so the timeline/audit panel refetch. If the tile should
   be hidden for certain roles (e.g. Staff can't see "Transfer Agent"), gate the `ActionTile`
   render with `useAuthContext().currentUser?.role`, matching how `isStaff` is used there
   today — don't rely on the backend 403 alone to hide UI a user shouldn't see at all.
4. **Timeline rendering** (`frontend/src/lib/interactionMeta.ts`) — add the new
   `interaction_type` to `TYPE_META` (icon/label/tone) and a `summarize()` case, or it
   falls back to a raw JSON dump on the timeline.
5. **Audit rendering** (`frontend/src/lib/auditLogMeta.ts`) — add the new
   `AuditEventType` to `EVENT_META`, or it falls back to a generic bullet. Mirror into the
   embedded copy's `lib/auditLogMeta.ts` too.
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
- If the action is role-restricted, exercise it as both an allowed role and a blocked role
  (e.g. Team Lead succeeds, Staff gets 403) — a permission gate with only the happy path
  tested is indistinguishable from no gate at all.
