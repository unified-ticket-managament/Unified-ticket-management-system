# First Feature Guide

A suggested way to get oriented: trace one small, real change through every layer, rather than reading the whole codebase linearly.

## Suggested first exercise: add a new SLA policy field

This touches every layer without requiring deep domain knowledge, and the SLA feature is among the best-documented and best-tested in the codebase — a good place to build confidence.

1. **Read the model**: `unified-backend/app/ticketing/models/sla_policy.py` — see the existing columns (`first_response_target_minutes`, `warning_1_percentage`, etc.).
2. **Read the schema**: `unified-backend/app/ticketing/schemas/sla.py` — the Pydantic request/response shape for `PATCH /sla/policies/{id}`.
3. **Read the service**: `unified-backend/app/ticketing/services/sla_service.py` — how a policy value is actually consumed (e.g. by `SLASweepService`'s threshold comparisons).
4. **Read the route**: `unified-backend/app/ticketing/api/sla.py` — the `sla_policy_router`, and its `sla:manage_policies` permission check.
5. **Read the migration pattern**: `unified-backend/alembic_ticketing/versions/b7f1d3e5a9c2_add_critical_sla_policy_row.py` — a real, recent example of adding an SLA-policy-related migration.
6. **Read the frontend**: `unified-frontend/src/app/(dashboard)/settings/sla-timing-matrix/page.tsx` — how the field would be surfaced for editing.
7. **Read the test**: `unified-backend/tests/test_sla_clock_math.py` — how a new field's effect on clock math would be tested.

Following this one field through all seven files teaches the API → Service → Repository → Model layering (see [05-technical-architecture/application-layers.md](../05-technical-architecture/application-layers.md)), the migration workflow, and the frontend's own data-fetching pattern — all in a low-risk, well-tested area.

## General approach for any first real feature

1. **Find the closest existing workflow document** in [03-business-workflows](../03-business-workflows/README.md) and read its "Relevant Source Files" section — this is your entry point into the code, curated specifically for this purpose.
2. **Check [16-known-limitations](../16-known-limitations/README.md) and [14-troubleshooting](../14-troubleshooting/README.md)** for anything relevant to the area you're touching — this codebase has an unusually rich, dated history of "this looked like X but was actually Y" incidents worth knowing before you rediscover one yourself.
3. **Grep before assuming** — several role-name/permission constants exist in more than one place across this codebase with **confirmed drift between them** (e.g. three different "supervisor role" definitions across frontend/backend). Never assume a constant's value without checking the specific file you're about to rely on.
4. **Write the regression test** — this codebase's own convention (see [11-testing/regression-testing.md](../11-testing/regression-testing.md)) is to add a test reproducing the exact failure mode whenever fixing a bug, not just exercise the happy path.
5. **Live-verify before calling it done** — per this project's own standing convention, "type-checked and unit-tested" is explicitly treated as a weaker claim than "live-verified against a running backend." Several features in this codebase's own history were flagged exactly this way pending a live check.
