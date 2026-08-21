# v2 Roadmap

## Intelligent Workload-Based Ticket Assignment & Transfer Recommendation

**Status: Planned, design-only — no code exists.** Captured in root `CLAUDE.md` ahead of implementation specifically so the design wouldn't be lost; this is the *only* forward-looking feature in the entire repository with a real design note behind it.

**Goal**: a ranking/scoring layer on top of the existing eligibility logic in `AssignmentService.get_assignable_groups`/`resolve_target` and `EscalationService.get_acknowledge_candidates` — both currently return an eligible, filtered *set* with no ordering signal. This would score and rank that set by current workload, so a supervisor sees "assign to X" instead of choosing blind.

**Explicitly not a replacement** for existing eligibility filtering — every RBAC/category/hierarchy constraint stays exactly as-is; this only reorders and annotates already-valid candidates.

**Proposed scoring signals** (phase 1, rule-based): open ticket count weighted by priority (`CRITICAL=6, HIGH=4, MEDIUM=2, LOW=1`); SLA-risk exposure of the agent's open tickets; active escalations currently owned; category/skill fit (mostly already implicit in existing eligibility filtering).

**Proposed architecture**: a new `WorkloadRepository` (aggregate `GROUP BY agent_id` queries, mirroring `UserRepository`'s existing shape — never per-candidate N+1) feeding a stateless `WorkloadScoringService`. `AssignmentService.get_assignable_groups` would gain an optional `rank_by_workload: bool`, additive to the current response shape.

**Explicitly out of scope for phase 1**: an ML/regression-based recommender (predicting resolution time per agent/category/priority) — floated as a distinct, later phase 2 idea, not to be folded into the same change as the rule-based scorer. Also out of scope: an availability/shift-presence table doesn't exist yet and would need its own migration before "filter unavailable candidates" could be enforced server-side.

See [04-functional-modules/assignment-management.md](../04-functional-modules/assignment-management.md) and [16-known-limitations/functional-limitations.md](../16-known-limitations/functional-limitations.md).

## Reporting Manager HR Action Surface

**Status: Deferred, not designed.** The business spec this feature was built from lists real HR actions (Approve/Reject Leave, View Attendance/Performance/Productivity/Timesheets/Team Reports, Conduct Reviews, Approve Work Logs, Team KPIs, Manage Team Members) that were **deliberately not built** — only the data-model/permission/assignment/org-chart plumbing exists. No design note for the action surface itself was found; this would be "a new epic, not an extension of this pass," per root `CLAUDE.md`'s own words.

## Ported Mail v2 design to the standalone frontend

**Status: Not planned, gap acknowledged.** The "Mail v2" two-panel redesign exists only in `unified-frontend`'s embedded ticket workspace copy. `ticketing-service/frontend` never received it, and as of the 2026-08-21 commit that added client filters/the OTP classifier, it no longer has anything at all to receive it into — even its former stale `dist/` bundle was deleted, leaving `ticketing-service/` empty. Porting this design back would first require rebuilding that frontend's source from scratch, which itself isn't a scheduled task anywhere found in this repository.
