# SLA & Escalation API

Source: `app/ticketing/api/sla.py` (two routers: ticket-scoped under `/tickets`, policy-scoped under `/sla`) and `app/ticketing/api/sla_internal.py` (`/internal/sla`). Services: `SLAService`, `EscalationService`, `EscalationHandlingSlaService`, `SLASweepService`. Full workflow narrative: [03-business-workflows/sla](../03-business-workflows/sla/) and [03-business-workflows/escalation](../03-business-workflows/escalation/).

## Ticket-scoped SLA/escalation — prefix `/tickets`

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/tickets/{id}/sla` | Current state of both SLA clocks | `get_current_user` + `ensure_agent_can_view_ticket_including_escalated` |
| POST | `/tickets/{id}/sla/pause` | Manually pause the Resolution SLA | `get_current_agent`; role-restricted in service |
| POST | `/tickets/{id}/sla/resume` | Manually resume a paused clock | `get_current_agent` |
| POST | `/tickets/{id}/escalate` | Manually raise/advance the internal escalation | `get_current_agent` + ticket visibility/ownership (not permission-gated — `ticket:escalate` is a defined but currently unenforced permission; see `EscalationService.manual_escalate`) |
| POST | `/tickets/{id}/escalation/acknowledge` | Acknowledge the current escalation level (step 1 of 2) | `get_current_agent` |
| POST | `/tickets/{id}/escalation/confirm-assignment` | Keep the current assignee (the one path that completes acceptance without `claim`/`transfer`) | `get_current_agent` |
| GET | `/tickets/{id}/escalation/acknowledge-candidates` | Role-scoped candidate list for Acknowledge & Assign | `get_current_agent` |

## SLA policy — prefix `/sla`

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/sla/policies` | List the SLA policy rows (one per priority tier) | `get_current_user` |
| PATCH | `/sla/policies/{id}` | Update one priority's SLA targets | `get_current_agent` + `sla:manage_policies` (Site Lead/Super Admin) |

## Internal sweep trigger — `app/ticketing/api/sla_internal.py`

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/internal/sla/sweep` | On-demand SLA breach-detection sweep | Shared secret only — `X-SLA-Sweep-Secret` header, compared via `secrets.compare_digest` against `settings.sla_sweep_shared_secret`. No JWT/user dependency at all. |

**This is a fallback, not the primary trigger.** The primary trigger is the in-process APScheduler job wired in `app/core/sla_scheduler.py`'s `lifespan` hook, firing on `SLA_SWEEP_INTERVAL_SECONDS` (default 10s locally, 60s in production per `render.yaml`). This endpoint exists for manual/emergency use and for the GitHub Actions `workflow_dispatch` fallback.

## Key business rules

**Two independent clocks**: First Response (founding interaction → first reply/OTP-match/triage action) and Resolution (creation → close, pausing on `WAITING_FOR_CLIENT`, reshifting on priority change).

**Four thresholds per clock**: `HALF_ELAPSED` / `AT_RISK` / `BREACHED` / `ESCALATED`, evaluated per sweep tick against per-priority-tier percentages (`SLAPolicy.warning_1_percentage`/`warning_2_percentage`, live-editable via the SLA Timing Matrix page — not hardcoded). Each `(clock, threshold)` pair notifies exactly once via an idempotency ledger.

**Escalation acceptance is two steps, not one**: `acknowledge()` only stops the ack-window auto-advance; it does **not** touch the Resolution SLA or start the Handling SLA. Only `_complete_acceptance` (reached via `acknowledge_via_assignment` — i.e. `claim`/`transfer` — or `confirm_assignment`) actually reshifts the Resolution SLA and starts `EscalationHandlingSLA`. This closed a real gap where a supervisor who acknowledged but never assigned had silently restarted the clock against nobody's ownership.

**Escalation starting level is dynamic**: one level *above* whoever currently owns the ticket (`_resolve_starting_level`) — not always `TEAM_LEAD`.

**Escalation-owner scoping**: the Escalated tab, Acknowledge, and `confirm-assignment` are all scoped to the escalation's current `owner_ids` (JSONB containment check) — a Site Lead/Account Manager/Super Admin cannot act on (or even have counted toward their queue) an escalation that hasn't reached their level yet. The former `GLOBAL_INBOX_ROLE_NAMES` bypass was removed from both `acknowledge()` and `confirm_assignment()`.

**CRITICAL priority is a side effect, not a separate action**: `_bump_priority_to_critical` runs as the first line of `_create_escalation` (shared by manual and automatic escalation) — idempotent, never reverts.

**Handling SLA breach auto-advances the escalation**: `SLASweepService.run_sweep` calls `EscalationHandlingSlaService.evaluate_breaches` at the end of every tick; a breach calls `EscalationService.advance_for_handling_sla_breach`, reusing the `ESCALATION_ADVANCED` audit event (tagged `reason: "escalation_handling_sla_breach"`).

## Side effects

- In-app notification + real outbound email (for `SLA_BREACHED`/`ESCALATION_CREATED`, per `EMAIL_ELIGIBLE_NOTIFICATION_TYPES`) on every threshold crossing.
- `PRIORITY_CHANGED` audit entry, attributed to `ActorRole.SYSTEM`, on the CRITICAL bump.
- `SLA_PAUSED`/`SLA_RESUMED` audit entries on every automatic or manual pause/resume (manual carries `"trigger": "manual_override"` in `new_values`).
