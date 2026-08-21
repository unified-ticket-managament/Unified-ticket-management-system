# Backlog

Every open item surfaced across this documentation pass, in one place. Each follows the required format.

---

**ID**: BL-01
**Title**: Workload-based ticket assignment/transfer recommendation (Phase 1, rule-based)
**Description**: Score and rank already-eligible assignment candidates by current workload.
**Business Value**: Reduces uneven ticket load across agents; supervisors get a real recommendation instead of a blind pick.
**Technical Value**: Adds one new repository + stateless scoring service; additive to existing response shapes.
**Priority**: Medium (inferred — no formal priority exists)
**Complexity**: Medium
**Dependencies**: None blocking — could start today.
**Current Status**: Planned, design-only.
**Proposed Version**: v2.
**Related Module**: [04-functional-modules/assignment-management.md](../04-functional-modules/assignment-management.md)
**Related Workflow**: [03-business-workflows/ticket/ticket-assignment.md](../03-business-workflows/ticket/ticket-assignment.md)
**Notes**: See [v2-roadmap.md](v2-roadmap.md) for the full design.

---

**ID**: BL-02
**Title**: ML-based resolution-time recommender (Phase 2)
**Description**: Predict resolution time per agent/category/priority via a trained model.
**Business Value**: Potentially more accurate recommendations than rule-based scoring.
**Technical Value**: N/A — no design exists.
**Priority**: Low (explicitly deferred)
**Complexity**: High (new data pipeline, training, drift monitoring)
**Dependencies**: BL-01, an availability/shift-presence data model, a data-protection review.
**Current Status**: Floated, not designed.
**Proposed Version**: Unscoped.
**Related Module**: [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md)
**Notes**: See [ai-automation-roadmap.md](ai-automation-roadmap.md).

---

**ID**: BL-03
**Title**: Reporting Manager HR action surface
**Description**: Approve/Reject Leave, View Attendance/Performance/Productivity/Timesheets/Team Reports, Conduct Reviews, Approve Work Logs, Team KPIs, Manage Team Members.
**Business Value**: Completes the Reporting Manager concept the org-structure feature already models.
**Technical Value**: N/A — a new epic.
**Priority**: Unknown — no scheduling signal found.
**Complexity**: High (multiple new subsystems).
**Dependencies**: None technical; needs a real spec.
**Current Status**: Deferred, deliberately not designed.
**Proposed Version**: Unscoped.
**Related Module**: [04-functional-modules/organization-structure.md](../04-functional-modules/organization-structure.md)

---

**ID**: BL-04
**Title**: Additive-only permission override model
**Description**: Add a mechanism for "role grants X, override revokes X for this person."
**Business Value**: Closes a real gap the permission matrix doc's next revision should address.
**Technical Value**: Requires a schema/scope change to `user_permission_overrides`.
**Priority**: Low-medium.
**Complexity**: Medium.
**Dependencies**: A revised permission-matrix source document.
**Current Status**: Deferred, explicitly noted as a limitation, not scheduled.
**Related Module**: [04-functional-modules/rbac-authorization.md](../04-functional-modules/rbac-authorization.md)

---

**ID**: BL-05
**Title**: Permissions for Related-Tickets link/unlink and Claim Ticket
**Description**: The RBAC permission matrix doc doesn't define a permission for either action.
**Business Value**: Closes a documentation/enforcement gap.
**Priority**: Low.
**Complexity**: Low.
**Current Status**: Noted, not scheduled.
**Related Module**: [04-functional-modules/rbac-authorization.md](../04-functional-modules/rbac-authorization.md)

---

**ID**: BL-06
**Title**: Availability/shift-presence data model
**Description**: A schema for online/leave/shift status, needed before any "filter unavailable candidates" feature.
**Business Value**: Prerequisite for more accurate assignment recommendations.
**Priority**: Low (no consumer feature is scheduled yet).
**Complexity**: Medium (new table, new migration, integration points across assignment logic).
**Current Status**: Not designed at all.
**Related Module**: [04-functional-modules/assignment-management.md](../04-functional-modules/assignment-management.md)

---

**ID**: BL-07
**Title**: Reconcile deployment-path ambiguity (Render vs. EC2) and update/retire `DEPLOYMENT.md`
**Description**: Determine which environment is authoritative production; rewrite or remove the stale 4-service runbook.
**Business Value**: Prevents a costly operational mistake (following the wrong runbook).
**Priority**: High.
**Complexity**: Low (mostly a documentation/decision task, not code).
**Current Status**: Unresolved as of this documentation pass.
**Related Module**: [09-deployment/README.md](../09-deployment/README.md)

---

**ID**: BL-08
**Title**: Fix the 3-file pytest-asyncio event-loop hang
**Description**: Add `asyncio_default_fixture_loop_scope` config or a per-test engine.
**Business Value**: N/A (developer productivity only).
**Priority**: Medium.
**Complexity**: Low-medium.
**Current Status**: Known, not fixed.
**Related Module**: [11-testing/integration-testing.md](../11-testing/integration-testing.md)

---

**ID**: BL-09
**Title**: Live-verify business-critical notification email against real SMTP
**Description**: Currently confirmed only via unit tests/import checks.
**Priority**: Medium.
**Complexity**: Low (a verification task, not a code change).
**Current Status**: Explicitly flagged as outstanding by the feature's own author.
**Related Module**: [04-functional-modules/notification-management.md](../04-functional-modules/notification-management.md)

---

**ID**: BL-10
**Title**: Real monitoring/alerting for scheduler and integration health
**Description**: No alert exists today for a stopped SLA sweep or a lapsed Graph webhook subscription.
**Priority**: Medium-high (silent failure risk).
**Complexity**: Medium.
**Current Status**: Not built.
**Related Module**: [10-operations/alerts.md](../10-operations/alerts.md)
