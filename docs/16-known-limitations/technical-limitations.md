# Technical Limitations

## Backend `app.rbac` has almost no server-side permission enforcement

**Limitation**: Nearly every RBAC route (Users/Roles/Permissions/Audit Logs) only checks *authentication* (`Depends(get_current_active_user)`), not *authorization*. Role-based UI hiding, permission-gated buttons, and hierarchy-based filtering are enforced **only in the frontend**. The one deliberate exception is the permission-overrides endpoints (`PermissionOverrideService.ensure_can_manage_overrides`) and the permission-request flow, plus (post the 2026-07-14/15 audit) a real `access_control.py` gate on Users/Roles/Permissions/Audit-Log routes for the highest-impact gaps found in that audit.
**Impact**: A crafted request bypassing the frontend can call almost any RBAC-domain endpoint with any authenticated account. Treat this as a known architectural characteristic, not something to silently "fix" without being asked — widening enforcement is a deliberate, scoped decision (see the compliance-audit section of root `CLAUDE.md`).
**Why It Exists**: Original historical design of the RBAC service, only partially hardened since.
**Current Workaround**: Frontend-side gating (`PermissionGuard`, role allowlists) is the only real control today for most RBAC routes.
**Is It Planned?**: Partially addressed (2026-07-14/15 audit); no further work scheduled.

## Two DB-touching pytest suites can't run in the same process

**Limitation**: `test_escalation_service.py`, `test_interaction_threading.py`, and `test_get_current_user_cache.py` each pass individually but **hang** if more than one runs in the same `pytest` invocation — a pre-existing `pytest-asyncio` issue (a module-level async engine's connection pool binds to whichever event loop existed when first used; a second test's fresh per-test loop can never complete operations queued against the first loop's transport).
**Impact**: CI/local test runs must isolate these files, or accept a hang.
**Why It Exists**: `pytest-asyncio`'s default per-test event-loop scope vs. a shared engine.
**Current Workaround**: Run DB-touching test files one at a time.
**Is It Planned?**: Not fixed — would need `asyncio_default_fixture_loop_scope` config or a per-test engine.

## `test_overdue_active_escalation_advances_without_touching_sla` is a known-flaky assertion

**Limitation**: This test asserts `evaluate_overdue` advances exactly 1 escalation, but `evaluate_overdue`'s query scans the entire `ticket_escalations` table (not just rows created in the test's own rolled-back transaction) — leftover `ACTIVE` rows from earlier manual/live testing in the shared dev database inflate the count.
**Impact**: Expect this specific test to fail against the shared dev database until either the test scopes its own assertion or the leftover rows are cleaned up.
**Why It Exists**: The test's isolation assumption doesn't hold against a shared, never-reset dev database.
**Current Workaround**: None — known, accepted flake.
**Is It Planned?**: Not fixed.

## In-memory, per-process caches — no cross-process/multi-worker support

**Limitation**: Both the RBAC session cache (`app/core/rbac_cache.py`) and the SSE pub/sub (`app/notifications/sse_manager.py`) are per-process, in-memory, with no Redis or shared broker.
**Impact**: Scaling the backend to multiple worker processes would break both — a permission change might not propagate to another worker's cache, and an SSE-connected client on one worker wouldn't see events published from another.
**Why It Exists**: Deliberate simplicity tradeoff for a single-uvicorn-process deployment.
**Current Workaround**: Run exactly one backend process (current deployment topology, per `render.yaml` — see [09-deployment](../09-deployment/README.md)).
**Is It Planned?**: Not scheduled; would require Redis or Postgres `LISTEN/NOTIFY` for multi-process support.

## RBAC cache staleness window

**Limitation**: A cache-hit session reconstructs the user from JWT claims without touching Postgres; RBAC changes (role/category/permission edits) are bounded to **at most one cache-TTL window** (default 30s) of staleness per process, not instant.
**Impact**: A permission grant/revoke or role change may not take effect for up to ~30 seconds for an already-authenticated session.
**Why It Exists**: Explicit, deliberate tradeoff to avoid a DB round trip on every request.
**Current Workaround**: None needed for most cases; be aware of it when testing a permission change "immediately."
**Is It Planned?**: No — accepted tradeoff.

## No availability/shift-presence data

**Limitation**: There is no schema or table tracking agent online/leave/shift status.
**Impact**: Any future "only assign to available agents" feature needs a new migration first.
**Why It Exists**: Never built.
**Current Workaround**: None.
**Is It Planned?**: Flagged as a prerequisite for the planned workload-ranking feature, not scheduled itself.

## SSE and RBAC cache degrade silently on very old tokens

**Limitation**: A JWT minted before the `permissions`/`scoped_permissions`/`name`/`role_id`/`category_id`/`permission_version` claims existed still decodes, but every enhancement built on those claims silently falls back to the slower/older code path (empty list/dict, or a full DB lookup) rather than erroring.
**Impact**: Mostly harmless (graceful degradation by design), but means a very old, still-valid refresh token can behave subtly differently until the next full login.
**Why It Exists**: Deliberate backward-compatibility design.
**Current Workaround**: None needed.
**Is It Planned?**: No — working as designed.
