# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Recurring convention below: many fixes were verified against a live backend/DB but not always through an actual browser session. Where a section says "not yet verified in a browser" (or similar), treat that specific claim as unconfirmed — don't extrapolate it to other features.

## Repo layout

Monorepo formed by merging three repos via `git subtree`, plus a later backend unification and frontend consolidation. `rbac-service/` no longer exists as a directory at all — don't trust any `rbac-service/...` or `ticketing-service/backend/...` path elsewhere.

- `unified-frontend/` — the shell app (formerly `rbac-service/frontend`, renamed once confirmed to be a strict superset of `ticketing-service/frontend`). Owns auth, session, roles/permissions/users, role-based routing, plus an embedded copy of the ticket workspace. Next.js 16. Has its own `CLAUDE.md` — read before working here.
- `ticketing-service/` — standalone, independently-runnable Vite/React ticket product with its own login flow. Its frontend is also embedded inside `unified-frontend`. Has its own `CLAUDE.md`; its backend-architecture sections describe history only.
- `shared_models/` — the one real copy of the `User`/`Role` SQLAlchemy models (local editable install). Never edit these from a service's own copy — there isn't one.
- `unified-backend/` — the actual, currently-running backend for everything. No `CLAUDE.md` of its own; this file covers it.

## Backend: one FastAPI app, not two

`rbac-service/backend/` and `ticketing-service/backend/` no longer exist as separate services — merged into `unified-backend/app/main.py`. `app/rbac/` (former `rbac-service/backend/app/`) mounts under `/api/v1`; `app/ticketing/` (former `ticketing-service/backend/app/`) mounts unprefixed — every route path is byte-identical to the old two-service setup, just one process on one port (`:8000`). `app/notifications/` is a third module alongside them. Two independent Alembic histories: `alembic_rbac/` and `alembic_ticketing/` (own `versions/`, own seed scripts under `scripts/rbac_seed/` / `scripts/ticketing_seed/`) — run `alembic -c alembic_rbac/alembic.ini upgrade head` then the ticketing equivalent (order matters only against an empty DB, since ticketing FKs into rbac's `users`). One Neon Postgres DB, one `unified-backend/.env` for both halves.

## Cross-service identity: RBAC issues, Ticketing verifies

Read "service" as "module" (`app.rbac` vs `app.ticketing`), not separate deployable. RBAC (`auth_service`) is the sole issuer of JWT access/refresh tokens (HS256); Ticketing is verify-only (decodes against the same `settings.jwt_secret_key`, no login/refresh endpoint of its own).

- **`permissions` claim**: role defaults ∪ active unscoped personal overrides, computed by `PermissionResolverService` at login/refresh.
- **`scoped_permissions` claim**: `dict[permission_name, list[ticket_id]]` for ticket-scoped overrides. Consumed via `access_control.has_permission`/`has_permission_for_ticket`/`ensure_has_permission` — decode-only, never a fresh RBAC call. A stale/absent claim degrades to empty rather than crashing; granting/revoking only affects the next login/refresh.
- **Session cache**: token also carries `name`/`role_id`/`category_id`/`category`/`permission_version`. `get_current_user` (`app/dependencies/auth.py`) checks an in-memory per-process TTL cache (`app/core/rbac_cache.py`, 30s TTL, keyed `(user_id, permission_version)`) — hit reconstructs a transient `User`/`Role`/`Category` from JWT claims with zero DB round trips; miss falls back to `UserRepository.get_by_id`, and a live `permission_version` mismatch is a hard 401 ("session outdated"). `permission_version` is bumped by `user_service.py` (role/category/manager/teamlead/active changes), `permission_override_service.py` (grant/revoke), `role_permission_service.py` (role-wide bulk `UPDATE`). `resolution_lock(user_id)` in the same file serializes concurrent cache misses per user to prevent a stampede on Postgres.
- **DB pool**: `pool_size=20, max_overflow=30, pool_timeout=10` (`app/database/session.py`) — raised from 10/20/default-30s after a frontend request-duplication bug oversubscribed it; don't raise further without checking Neon's connection ceiling.

## The ticket workspace exists in two places

`ticketing-service/frontend`'s entire page tree is also copied (not linked) into `unified-frontend/src/ticket-workspace/` (imports via `@tw/*` instead of `@/*`) and mounted in the Next.js shell via `react-router-dom`. **These do not stay in sync automatically** — a ticket-page/component/API-wrapper change generally needs porting to both; check which is actually deployed before assuming one-sided is enough. Both call the same `unified-backend`, via different base-URL env vars (`VITE_API_BASE_URL`, `NEXT_PUBLIC_TICKETING_API_URL`) that should both point at the unified backend's root (no `/api/v1`).

The gap has widened, not narrowed: Mail v2 (two-panel layout, redesigned Message Details, auto-saving Draft) exists **only** in the embedded copy — the standalone app's Mail/Inbox still reflects the older design. The two `CLAUDE.md`s' Mail sections no longer describe the same UI. **Update, 2026-08-21: the standalone `ticketing-service/frontend` directory was deleted entirely** in commit `65f6cd9` — this "keep both in sync" guidance is now stale for any future Mail-UI change, since there's no second copy left.

## Local development

```bash
cd unified-backend && bash scripts/start.sh     # :8000 — runs both Alembic chains, then uvicorn
cd unified-frontend && npm run dev              # :3000, embeds the ticket workspace
```

`scripts/start.sh` needs `unified-backend/.env` (`DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `JWT_SECRET_KEY`/`JWT_ALGORITHM`, storage vars — see `Settings` in `app/core/config.py`). Individually: `alembic -c alembic_rbac/alembic.ini upgrade head`, `alembic -c alembic_ticketing/alembic.ini upgrade head`, `uvicorn app.main:app --reload --port 8000`. `Settings` is `@lru_cache`d — `.env` edits need a full restart; `--reload` only reacts to `.py` changes and has been unreliable on Windows.

**Gotchas:**
- Don't trust `--reload`'s "Reloading..." log line as proof a fix is live — compare the running worker's start time against the edited file's mtime. Killing uvicorn's reported PIDs doesn't reliably clean up orphaned `python.exe`/stale socket entries either. Reliable sequence: kill *every* python/uvicorn process → confirm the port is free (`Get-NetTCPConnection -LocalPort 8000`) → start exactly one fresh process → verify via a real `httpx`/`curl` request (with `Origin` header) hitting the actual route, not just a direct service-method call.
- A `git pull` that merges a teammate's committed changes into a file you have *uncommitted* changes in can silently discard your side with no conflict marker — git's 3-way merge has nothing to diff against work that was never committed. `git status`'s `UU` list only shows textual conflicts, not this. Commit WIP (even to a throwaway branch) before pulling; afterward, explicitly re-check every file you touched against the merged result.
- Both frontends must point their ticketing API base URL at the unified backend's root (`:8000`), not the old standalone `:8001` — `unified-frontend` silently defaults to `:8001` if `NEXT_PUBLIC_TICKETING_API_URL` is unset, network-erroring every ticketing-domain request while RBAC-native requests keep working. Set it in `.env.local` and restart (`NEXT_PUBLIC_*` is baked in at server start).
- `WinError 10013` on `uvicorn --reload` almost always means a previous process already holds port 8000, not a permissions issue — check `Get-NetTCPConnection -LocalPort 8000`, kill all python/uvicorn processes, restart.
- Starting the backend with a bare `python -m uvicorn` instead of `.venv\Scripts\python.exe` can silently resolve `shared_models` to a stale, unrelated install elsewhere on `PATH`, producing confusing `TypeError: invalid keyword argument` 500s on any newer model field, unrelated to whatever was just changed. Always use the project's own `.venv` interpreter.

## Deployment

Render.com via the single root `render.yaml`: `unified-backend` (Web Service), `rbac-frontend` (Web Service, `rootDir` now `unified-frontend` — service name kept unchanged for URL stability), `ticketing-frontend` (static site). See `DEPLOYMENT.md`. Rotating `JWT_SECRET_KEY` in prod invalidates every token immediately (global logout) — schedule deliberately.

**The deployed Render backend and a developer's local backend share the same Neon DB by default, and each runs its own independent in-process SLA scheduler** — a local SLA/escalation fix can look like it's "not working" because the deployed instance is racing the same rows. Either suspend the Render service during testing, or (better) create a Neon branch and point local `DATABASE_URL`/`ALEMBIC_DATABASE_URL` at it.

The SLA sweep runs in-process via APScheduler (`app/core/sla_scheduler.py`, wired into `main.py`'s `lifespan`) — GitHub Actions' `sla-sweep.yml` is a manual/emergency fallback only (`workflow_dispatch`, shared-secret `POST /internal/sla/sweep`), not the trigger. The interval setting is **`SLA_SWEEP_INTERVAL_SECONDS`** (seconds, default 10 locally; `render.yaml` sets `"60"` for prod) — don't assume the two environments run the same cadence, and don't reintroduce a second external scheduler (escalation logic depends on exactly one sweep trigger per tick).

## SLA & Escalation

Lives entirely in `unified-backend/app/ticketing/` — never ported to standalone `ticketing-service/frontend`. SLA UI only in `unified-frontend/src/ticket-workspace/components/sla/`.

Two independent per-ticket clocks:
- **First Response SLA** — starts on the founding interaction, completes on first agent reply (or OTP auto-completion, see below).
- **Resolution SLA** — starts at ticket creation, pauses during `WAITING_FOR_CLIENT`, reshifts `due_at` on priority change, completes only on `CLOSED` (not `RESOLVED`).

Targets/thresholds come from `SLAPolicy` (per-priority-tier row, not hardcoded) — `warning_1_percentage`/`warning_2_percentage`/`handling_sla_percentage` editable live via the Super-Admin SLA Timing Matrix page. `SLASweepService.run_sweep` evaluates thresholds (`HALF_ELAPSED`/`AT_RISK`/`BREACHED`/`ESCALATED`), records each crossing in an idempotency ledger (notifies once), fires an in-app notification + email. First Response notifications link to the specific message (`/inbox?interaction_id=...`) with real subject/client/body-snippet content.

**Escalation workflow** (`TicketEscalation`/`EscalationService`) sits on top of, but never touches, Resolution SLA's own `started_at`/`due_at`/`status` columns.
- Auto-creates on first `BREACHED`/`ESCALATED` crossing (`auto_escalate_if_needed`, no-op if already active); manual trigger needs `ticket:escalate`; auto-advances `TEAM_LEAD → MANAGER → SITE_LEAD` if `ack_due_at` lapses (`evaluate_overdue`, same sweep tick).
- Starting level is dynamic — one level above the current owner (Staff/unclaimed → `TEAM_LEAD`; Team-Lead-owned → `MANAGER`; AM-owned → `SITE_LEAD`), falling forward if a level has zero owners.
- `SLA_ESCALATED` (SLA notification tier) vs `ESCALATION_CREATED`/`_ACKNOWLEDGED`/`_ADVANCED`/`_CLOSED` (ownership-chain events) are distinct `AuditEventType` values — don't conflate.
- `UserRepository.list_active_by_role_and_category`/`list_active_staff_by_category` validate `category_name` against real `CategoryName` values in Python before querying — a corrupted `ticket_type` used to crash the whole sweep tick (a savepoint believed to isolate it did not); now just yields "no one found."
- `SLA_PAUSED`/`SLA_RESUMED` (renamed from `SLA_MANUALLY_*`) log on every `WAITING_FOR_CLIENT` enter/exit, not just manual overrides — the manual path is distinguished only by a `trigger: "manual_override"` key in `new_values`.
- Three Postgres-native enums: `SLAClockStatus`, `EscalationLevel`, `EscalationStatus` — see `ticketing-service/CLAUDE.md`'s "add-postgres-enum-value" skill before adding a member to any of these or `AuditEventType`.

**`EscalationHandlingSLA`** (own table) measures time-to-resolve once the escalation owner accepts — independent of Resolution SLA/`TicketEscalation`'s own columns. Target = 25% of the *original* Resolution SLA target, computed once. Started only by `EscalationService._complete_acceptance` (idempotent — never restarts), reached via `acknowledge_via_assignment` (assign/claim during escalation) or `confirm_assignment` (keep current assignee). **A bare Acknowledge click does not start it or reshift Resolution SLA** — that only happens after Acknowledge *and* Assign (`acknowledge()` only stops the ack-window auto-advance). The previous-owner freeze (`ensure_agent_can_act_on_ticket`) checks for a real `EscalationHandlingSLA` row when a repository is supplied, else falls back to the coarser `status == ACTIVE` check (e.g. `AttachmentService.upload_attachment` still uses the coarser check). Breaches advance the escalation level via `evaluate_breaches` in the same sweep tick.

**Escalated tab** (`view=escalated` on `GET /tickets`, role-gated to Team Lead/AM/Site Lead/Super Admin) uses the same visibility scoping as other views plus a strict `owner_ids` JSONB containment check — a ticket only appears in someone's Escalated queue once escalation has actually reached their level, never earlier via generic role-based visibility (the old "Site Lead/Super Admin are global overseers" bypass was removed from `acknowledge()`/`confirm_assignment()` for the same reason). `is_escalation_owner` on ticket responses lets the frontend hide the Acknowledge button on broader views (e.g. All Tickets). Acknowledge & Assign's candidate picker (`GET /tickets/{id}/escalation/acknowledge-candidates`) is role-scoped: Site Lead/Super Admin → category's Team Lead(s) + client's AM; AM → own category-matched Team Lead(s); Team Lead → category's Staff. Unclaimed escalated tickets are excluded from Open Pool (reachable only via the Escalated tab), `agent_id` stays null.

**Known test fragility**: DB-touching test files (`test_escalation_service.py`, `test_interaction_threading.py`, `test_get_current_user_cache.py`) hang if more than one runs in the same pytest process (pytest-asyncio event-loop-scope issue, not fixed) — run them one file at a time. `test_escalation_service.py`'s `evaluate_overdue` test also scans the whole `ticket_escalations` table, so leftover dev-DB rows can inflate its assertion — known, not fixed. If an SLA/escalation bug report looks structural, check `alembic -c alembic_ticketing/alembic.ini current` vs `heads` first — a stale dev-DB schema has produced `UndefinedColumnError` 500s that were mistaken for logic bugs before.

## CRITICAL priority: escalation-only, permanent

`TicketPriority.CRITICAL` is a real, filterable priority value, never manually selectable anywhere (backend or frontend). Its only writer is `EscalationService._bump_priority_to_critical` (idempotent, called first in `_create_escalation` for both manual and auto escalation) — it never reverts, and reuses `SLAService.reshift_resolution_clock_for_priority_change` so the Resolution SLA clock's `priority` column (what the sweep math actually keys off) stays consistent. `SLAPolicy` row for CRITICAL: 5min First Response, 60min Resolution, 10min Ack Window, 25% Handling SLA, 50%/80% warning tiers. Distinct from the pre-existing display-only "CRITICAL" badge shown for `is_escalated` tickets. No ongoing backfill mechanism exists — a future bump-logic bug would again require a manual one-off data-fix script (one was already run once, to backfill tickets that had escalated before this feature landed).

## OTP detection → Response SLA auto-completion

First Response SLA now auto-completes via a semantic classifier, not rule-based keyword matching (superseding an earlier, simpler "OTP Rule category match" trigger that couldn't distinguish a genuine code delivery from an email merely mentioning "OTP"). `app/ticketing/services/otp_classifier.py`'s `classify_otp_email(subject, body, *, threshold)` is pure/no I/O: a qualifying code noun + a code-shaped 4-8 digit number are the two primary signals and are together sufficient; usage-instruction/expiration language are bonus signals; a hard confidence ceiling (0.30) applies when support-request/complaint framing is detected. Threshold is `Settings.otp_nlp_confidence_threshold` (default `0.90`).

`EmailService.receive_email` completes the Response SLA from this classification alone, **before** the Mail/OTP Rules engine even runs — fully independent of rule matching/forwarding, which is otherwise unchanged and still handles folder/forward actions off its own `RuleCategory.OTP_RULE` check. Note: a rule's `client` condition (if present) is an exact-match filter, not "this client + any client with none" — a misconfigured condition can silently make a rule never fire for the client its name implies.

Mail's First Response SLA badge now reflects real backend state (`first_response_sla` field on `OpenEmailResponse`/`InboxItemResponse`) instead of pure client-side estimation, so a completed clock doesn't keep showing a live countdown.

## RBAC permission compliance audit (2026-07)

Full audit of every permission in the RBAC matrix doc against actual enforcement (detail in `ticketing-service/CLAUDE.md`'s "Roles"/"SLA workflow" and `unified-frontend/CLAUDE.md`'s matching sections). Key fixes:
- `AttachmentService.upload_attachment`'s auth check was called without `await` — silently never ran; any agent could upload to any ticket. Fixed.
- Team Lead's unconditional bypass on Close/Reopen/manual SLA override narrowed to `CLOSE_REOPEN_BYPASS_ROLE_NAMES` (Site Lead/Super Admin only).
- Account Manager's own-clients visibility, previously enforced only on ticket view, extended to every mutating action (priority/category/status change, transfer, reply, hide-interaction, audit view, attachments, SLA override).
- `app.rbac` had zero backend permission enforcement before this — added `app/rbac/services/access_control.py`, wired into Users/Roles/Permissions/Audit-Log routes. Highest impact: `PUT /roles/{id}/permissions` had no backend gate at all.
- `scripts/rbac_seed/seed.py` reconciled to match the doc (renamed/split/added several permissions, corrected several over/under-privileged defaults).
- Ticket-workspace Audit Log page reworked into a scoped-by-default view (no permission required) plus an opt-in centralized mode gated by `ticket:view_global_audit_log`.
- Known, deliberate scope limitations: personal permission overrides are additive-only (no "role allows, override revokes" path); Related Tickets link/unlink and Claim Ticket have no permission in the matrix doc at all.

## Organization Structure (2026-07-17)

A business hierarchy, deliberately separate from the RBAC role ladder — three independent relationships that must never collapse into one:
1. Real reporting line (`User.manager_id`/`teamlead_id`).
2. **Reporting Manager mapping** (new `reporting_manager_teams` table) — many-to-many Account Manager ↔ Category, an *additional* HR responsibility layered onto an existing AM (never a new role). Gated by `org:manage_reporting_managers` (Super Admin/Site Lead only).
3. **Ticket-assignment capability** — any Account Manager can hand tickets to any Team Lead company-wide (widened from the old `manager_id`-scoped list). A Staff target is now unconditionally category-scoped in `transfer_agent` (previously only during active escalation).

`UserService._validate_manager_and_teamlead` now validates role/category consistency for `manager_id`/`teamlead_id` (previously only existence was checked). `OrganizationService` builds a dynamic, per-profile org chart (the full chain top-down through the viewed profile, then down through their own subordinates) rather than one static tree — downward expansion tags each Team-Lead-under-AM edge as `reports_to`/`reporting_manager`/`assignable`; upward expansion stays narrow (only the viewed profile's real ancestors, never fanning into siblings' unrelated branches). `_build_subtree`/`get_subordinate_user_ids` (permission-override grant scoping) are deliberately untouched — still real-reporting-line-only. Scope note: only the data-model/permission/assignment/org-chart plumbing was built; no HR action surface (Leave approval, Attendance, Timesheets, etc.) exists yet.

## Profile module (2026-07-17)

Ten new nullable `shared_models.User` columns (`date_of_birth`, `alternate_email`, `phone_number`, `office_location`, `department`, `team`, `language`, `date_format`, `time_format`, `time_zone`, `default_dashboard`) replaced the old client-only Zustand mock store. `department`/`team` are independent of `category_id` (display-only, no RBAC weight). "Employee ID" on Profile is `user.user_id` (or `employee_number`, see below) — never a fabricated `EMP-#` string. `PATCH /auth/me` persists 9 of the 10 fields (all but `team`, display-only).

Fixed bug: on an RBAC-cache hit, `get_current_user` returns a transient (non-session-attached) `User`; `update_profile`'s `db.refresh()` on it 500'd. Fixed by re-fetching a real session-attached row before mutating. `change_password` has the identical latent bug, not yet fixed.

## Notifications: SSE push (2026-07-22)

`GET /notifications/stream` (SSE) replaced 30s polling. `app/notifications/sse_manager.py`'s `NotificationStreamManager` — in-memory per-process pub/sub keyed on `user_id` → set of `asyncio.Queue` (one per open tab). `NotificationService.notify()` publishes immediately after creating rows; no-op if no subscribers. Per-process only (no Redis), same tradeoff as `rbac_cache`. Authenticated via `get_current_user_sse` (token as `?token=` query param — `EventSource` can't set headers) which deliberately does **not** hold a pooled DB connection for the stream's lifetime (opens/closes its own short-lived session just for the auth check) to avoid exhausting the pool with long-lived connections. Heartbeat comment every 25s doubles as disconnect detection.

## Notifications: business-critical types also email (2026-08-06)

Centralized policy: `app/notifications/email_policy.py`'s `EMAIL_ELIGIBLE_NOTIFICATION_TYPES` frozenset (`TICKET_ASSIGNED`, `ESCALATION_CREATED`, `SLA_BREACHED`, `CLIENT_REPLY`, `EDIT_ACCESS_APPROVED`, `EDIT_ACCESS_REJECTED`) — the one place to edit to add/remove a type from email delivery. Hooked into `NotificationService.notify()` itself (never-raise try/except) — zero changes to any of the ~17 existing call sites. Delivery is async via `asyncio.create_task` on its own fresh `AsyncSessionLocal` session (works because that factory is `expire_on_commit=False`). Reuses the existing `EmailSender`/`SMTPEmailSender` transport (extended with an optional `html_body` param). Recipient resolution uses a new `get_active_emails_by_ids()` that skips deactivated users. Ticket context in the email body is best-effort — only populated when `related_entity_type == "ticket"`. Not live-verified against real SMTP/inbox, only unit-test/import level.

## Employee data cleanup (2026-08-10)

Removed 25 dummy/demo accounts (matched by email against the official 99-employee master list, never by fuzzy name) from a 125-row `users` table. Two explicit exceptions kept: `umesh@probeps.com` (real Site Lead), `admin@rbac.com` (Super Admin). `Gogineni@painmedpa.com` deliberately kept as-is despite being a likely misspelling of `pavan@probeps.com`. Deletion required enumerating all 30 FK columns referencing `users.user_id` via `information_schema` catalogs — don't assume you know the full FK graph without checking that catalog first. `scripts/rbac_seed/seed.py`'s `DEMO_USERS` collapsed to just Super Admin so dummies can't reappear on reseed.

## `employee_number` column (2026-08-10, gap fixed 2026-08-18)

Additive `users.employee_number` (nullable, unique) alongside the UUID `user_id` — every FK/auth-claim/relationship still keys off the UUID. Backfilled by email match against the official employee list (98/99 matched). Exposed in `CurrentUser`, `UserResponse`/`UserUpdate`, `AssignableUserSummary`, `AgentSummaryResponse`. Frontend renders "Name (ID)" via `formatAssigneeLabel()`. Gap fixed 2026-08-18: Create User form had no field for it and `create_user` silently dropped it — now required for the 5 internal roles (Client exempt), validated unique via `UserRepository.exists_by_employee_number`. Not yet verified in a browser.

## Ticket numbering TKT-XX (2026-08-10)

`tickets.ticket_number` is backed by a real Postgres `SEQUENCE` (`ticket_number_seq`), concurrency-safe by construction. A real bug existed in the *data*, not the mechanism: an earlier one-time backfill ranked tickets against a since-deleted larger population, producing non-contiguous numbers. Fixed via a second migration that re-ranks only the current live population and resets the sequence — a one-time re-normalization only; future deletions are expected to reintroduce gaps and that's fine (the guarding test in `tests/test_ticket_number.py` deliberately doesn't assert zero gaps). One test in that file has the same known pytest-asyncio event-loop flake as other DB-touching test files.

## Internal Note recipients (2026-08-11)

Internal Note's "To" field is now real (was previously UI-only). `InternalNoteCreate.recipient_user_ids` (optional; empty preserves the old auto-notify-stakeholders fallback). Stored in the Interaction's existing `payload` JSON — no new table. Three bugs fixed in the same pass: (1) the Timeline list endpoint's payload-trimming helper dropped the new recipient fields before they reached the frontend; (2) the note-creation route never constructed a `NotificationService` at all, so `notify()` had never fired through this route, ever; (3) RBAC's `GET /users`/`GET /roles` are hierarchy/permission-scoped, breaking the old picker for non-privileged senders — fixed with a new unscoped `GET /tickets/internal-notes/recipients` endpoint (gated only by `get_current_agent`), since RBAC's own endpoints couldn't be widened without changing their general-purpose scoping. CC/BCC remain UI-only with no backend delivery — out of scope.

## Forwarded mail 403 fix (2026-08-15)

Opening mail forwarded to an internal user 403'd even with `communication:view_all` granted, because `ensure_agent_can_view_pending_interaction` never checked any RBAC permission (only Site Lead/Super Admin/owning AM). Fixed by adding a `view_only` flag that additionally admits `communication:view_all` holders — used only by `OpenEmailService.get_email_details`, never by the pending-item *action* methods (claim/archive/reply/etc.), so it only widens "can open and read", never "can act on". Not yet verified as two real logged-in users.

## Inbound Graph attachments (2026-08-16)

Three independent bugs, all had to be fixed together for real attachments to work:
1. `build_upload_files_from_graph_attachments` rejected every attachment because Graph only returns `@odata.type` when explicitly `$select`ed (the original select fields never did), so every real attachment parsed as `odata_type=None` and got excluded. Fixed to only exclude an explicitly-mismatched type.
2. `validate_attachment_type` rejected attachments where Graph reported a generic `application/octet-stream` even though the extension was allow-listed — now just logged, not rejected (the extension allow-list is still the real security gate).
3. **The actual live blocker**: `fetch_message_attachments`'s Graph `$select` (including `contentBytes`) 400'd on every real attachment call — `contentBytes` only exists on the derived `fileAttachment` type and Graph rejects selecting it on the polymorphic base type. Fixed by removing `$select` entirely from that call.

Not a bug: Outlook's "Attach as cloud link" inserts an HTML link into the body instead of a real Graph attachment (Graph's attachments collection never sees it) — handled by the feature below.

## OneDrive/SharePoint cloud-link attachments + named-link href preservation (2026-08-21)

Confirmed live against real Graph: a cloud-link share produces `hasAttachments: False` and an empty attachments collection — the file's only trace is an `<a>` anchor in `body.content` (Outlook's `_EType_OWALink` card), whose `href` (or Safe-Links `originalsrc`) is the real share URL. `mail_mapping_service.extract_cloud_link_attachments()` scans for anchors matching `CLOUD_LINK_HOST_MARKERS` (sharepoint.com/1drv.ms/onedrive.live.com) and creates a distinct, non-downloadable "linked attachment" row (`attachments.storage_key` now nullable, plus new `external_url`/`is_external_link` columns) rather than a normal Attachment. All attachment read paths (`attachment_to_metadata`, resend, download, delete) branch on `is_external_link`. Frontend: `MessageDetailsView.tsx`, shared `AttachmentList.tsx`, and `TicketAttachmentsTab.tsx` each gained an external-link branch.

A second, distinct bug found while verifying: Outlook's "Insert > Link" (a custom display label, unrelated to cloud storage) loses its href the same way plain-text extraction always did. Fixed with `_preserve_named_link_hrefs()`, rewriting `label (href)` into the text before `get_text()` runs, so the frontend's existing auto-linkifier picks it back up. Two cloud-link test emails sent before this fix landed were not backfilled.

## Gmail delivery gap — DNS/DKIM issue, not an app bug (2026-08-21)

Traced the full outbound path and confirmed no application bug: Graph accepts (202) every send regardless of recipient domain, and the app has zero bounce/DSN/delivery-status visibility at all (`dispatch_status: "SENT"` only ever means "Graph accepted it"). Root cause is external: `probeps.com` has no DKIM (`selector1/2._domainkey` NXDOMAIN) and no DMARC (`_dmarc` NXDOMAIN) — SPF alone is enough for Microsoft-to-Microsoft delivery but not for Gmail's spam classifier. Fix is in Microsoft 365 admin + the DNS registrar, not in this repo. Not yet re-verified after any DNS fix.

## Super Admin "Login as User" impersonation (2026-08-22)

A Super Admin can temporarily assume another (non-Super-Admin, non-self) user's identity/permissions. No nested impersonation.

- `ImpersonationService.start` mints a token pair whose identity claims are the TARGET's (computed via the normal `PermissionResolverService`) — every existing ~30+ authorization/visibility call site needs zero changes. The actor's real identity survives only as additive `impersonator_id`/`impersonator_name`/`impersonation_session_id` claims, read only by audit-writing code.
- A per-request `contextvars.ContextVar` (set/cleared every request) is read by both `AuditLogRepository.create()` implementations, stamping new nullable `impersonator_id`/`impersonator_name` columns on `audit_logs` and `ticket_audit_logs` — no changes needed to any existing logging call site.
- A new `impersonation_sessions` table provides revocability a stateless JWT can't — any token carrying `impersonation_session_id` triggers one extra, never-cached DB lookup validating session status/expiry/both parties' `is_active`, so "Exit Impersonation" or deactivating either party takes effect immediately.
- Permission revocation mid-session needs no new code — caught by the existing `permission_version` mismatch check on the next cache miss.
- Impersonation refresh tokens re-mint a target-shaped pair capped at the *original* session's `expires_at` — never extending it.
- Endpoints: `POST /admin/impersonation/start` (`user:impersonate`, rejects Super-Admin targets), `POST /admin/impersonation/end` (reads actor identity off the token's `impersonator_id` claim).
- Seeding bug caught before shipping: the "Site Lead gets every permission except two" seed logic had auto-granted `user:impersonate` to Site Lead too — excluded and clawed back in `scripts/rbac_seed/seed.py`.
- Frontend hard-navigates (`window.location.href`) on start/end, since several session-scoped caches (SSE stream, React Query, workspace's "once per session" fetches) only reliably reset on a full page load.
- Not yet verified: an actual browser click-through, and a real permission-revoked-mid-session request.

## PLANNED (not implemented): Workload-based assignment ranking

Design-only — no code exists yet. Would add a ranking/scoring layer on top of `AssignmentService.get_assignable_groups`/`resolve_target` and `EscalationService.get_acknowledge_candidates` (currently return an eligible set with no ordering) — score by open-ticket count (priority-weighted), SLA-risk exposure, active escalations owned, category fit. Proposed: a new `WorkloadRepository` + stateless `WorkloadScoringService`, an optional `rank_by_workload` flag on `get_assignable_groups`. ML-based recommendation and an availability/shift-presence table are explicitly out of scope for a first pass. Update or remove this section once real work lands.
