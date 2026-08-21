# Functional Limitations

## No workload-based assignment ranking

**Limitation**: When a supervisor picks who to assign/transfer/acknowledge-and-assign a ticket to, the candidate list (`AssignmentService.get_assignable_groups`, `EscalationService.get_acknowledge_candidates`) is RBAC/category/hierarchy-filtered but **unordered by workload** — there is no "this person has fewer open tickets" signal anywhere.
**Impact**: A supervisor can accidentally pile tickets onto an already-overloaded agent; no system-provided recommendation exists.
**Why It Exists**: Never built — see the "PLANNED" design note in root `CLAUDE.md`.
**Current Workaround**: Manual judgment by the supervisor.
**Is It Planned?**: Yes — design-only as of 2026-07-27, no code written. See [17-roadmap/v2-roadmap.md](../17-roadmap/v2-roadmap.md).

## Reporting Manager HR actions not built

**Limitation**: The Reporting Manager assignment/mapping (Account Manager ↔ Category) exists at the data/permission/org-chart level, but none of the actual HR action surface the business spec describes (Approve/Reject Leave, View Attendance/Performance/Productivity/Timesheets/Team Reports, Conduct Reviews, Approve Work Logs, Team KPIs, Manage Team Members) has any UI or backend endpoint.
**Impact**: "Reporting Manager" today is purely an assignment/visibility concept, not a functioning HR workflow.
**Why It Exists**: Deliberately scoped out — confirmed, not an oversight, per root `CLAUDE.md`'s Organization Structure section.
**Current Workaround**: None; these actions don't exist anywhere in the product yet.
**Is It Planned?**: A new epic, not scheduled. See [17-roadmap/backlog.md](backlog.md — see roadmap folder).

## Permission overrides are additive-only

**Limitation**: `user_permission_overrides` can only *grant* a permission a user's role doesn't already include. There is no mechanism for "role grants X, but revoke X for this one person."
**Impact**: A "role allows, override revokes" scenario can't be built without a schema/scope change.
**Why It Exists**: Deliberate architectural scope call, noted during the RBAC permission-compliance audit (2026-07-14/15).
**Current Workaround**: None.
**Is It Planned?**: No open item; flagged for whoever next revises the permission matrix doc.

## Related Tickets link/unlink and Claim Ticket have no matrix-defined permission

**Limitation**: These two actions exist in the product but the RBAC permission-matrix document (the audit's ground truth) doesn't define a permission covering either.
**Impact**: Enforcement for these two actions is whatever the code happened to implement, not something traceable to an agreed permission.
**Why It Exists**: Gap in the source-of-truth doc, not the code.
**Current Workaround**: None.
**Is It Planned?**: Noted for the permission-matrix doc's next revision; no ticket exists.

## CC/BCC on ticket replies and Internal Note recipients are UI-only for some paths

**Limitation**: Reply's CC/BCC fields are plain optional text with no backend delivery concept beyond being passed through the existing `ReplyRequest.cc`/`.bcc`. Internal Note's own informational "To" role-grouped dropdown (as distinct from the newer real recipient-delivery feature — see [Internal Note Recipients workflow](../03-business-workflows/README.md)) is not sent to the backend at all in some UI surfaces.
**Impact**: Some recipient-selection UI is cosmetic/informational only, not a delivery guarantee — verify per specific feature before assuming "selecting someone" always notifies them.
**Why It Exists**: Incremental feature scoping across multiple work sessions.
**Current Workaround**: None; check the specific composer feature's implementation before relying on it.
**Is It Planned?**: Not tracked.

## AI/NLP capabilities: not confirmed in current code

**Limitation**: No AI/LLM-based ticket classification, response drafting, or escalation-processing logic was found during this documentation pass.
**Impact**: The functional-modules "AI/NLP" document should be read as **Not Implemented** unless a future audit finds otherwise.
**Why It Exists**: Not built as of this writing.
**Current Workaround**: N/A.
**Is It Planned?**: Not confirmed — see [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md).

## Standalone `ticketing-service/frontend` no longer exists (decommissioning completed 2026-08-21)

**Limitation**: A second, independently-runnable Vite/React ticket-workspace frontend used to exist in the repository (later reduced to a stale, pre-built `dist/` bundle with no source). As of the 2026-08-21 commit that added client filters and the OTP classifier, even that `dist/` bundle was deleted — `ticketing-service/` is now an empty directory.
**Impact**: None going forward for development — `unified-frontend` was already the only maintained frontend before this; there is now nothing left at this path to accidentally edit or confuse with the embedded copy.
**Why It Exists**: `unified-frontend` was confirmed to be a strict superset once the embedded copy was built; the standalone app was kept only for historical/reference reasons, then removed once that reference value was judged no longer needed.
**Current Workaround**: N/A — nothing to work around; `unified-frontend` is unambiguously the only frontend.
**Is It Planned?**: N/A — this was the "separate, later" decommissioning step previously described as not-yet-done; it is now done.
