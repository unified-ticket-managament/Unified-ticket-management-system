# API Testing

## What exists

No dedicated HTTP-level API test suite (e.g. using FastAPI's `TestClient`/`httpx.AsyncClient` against actual routes end-to-end) was confirmed as a distinct category in this pass — the 48 test files in `unified-backend/tests/` predominantly exercise **service-layer** functions directly (`EscalationService`, `SLAService`, etc.) rather than making HTTP requests through the FastAPI route layer.

This means: **a bug in a route's own request/response schema, dependency wiring, or FastAPI-level validation could exist without any test catching it**, even if the underlying service logic is well-tested. Root `CLAUDE.md`'s own troubleshooting history confirms this gap has mattered in practice — several real bugs (the `AttachmentService.upload_attachment` missing `await`, the RBAC-domain permission checks) were found via manual/live testing against a running backend, not via an automated API test.

## What partially covers this gap

- `test_sla_sweep_auth.py` (3 tests) — specifically tests the shared-secret auth on `POST /internal/sla/sweep`, at what appears to be closer to the route/dependency level.
- Root `CLAUDE.md` repeatedly documents a manual pattern used in place of automated API tests: **mint a real token and hit the actual route with `httpx`/`curl`** (including the `Origin` header a browser sends) rather than only exercising the service method directly — this is the de facto API-testing method used throughout this project's history, just not codified as an automated suite.

## Swagger/OpenAPI as a manual testing tool

`/docs` (Swagger UI) and `/redoc` are always available against a running backend and are the practical way to manually exercise an endpoint's exact request/response shape — see [13-developer-onboarding/swagger.md](../13-developer-onboarding/swagger.md).

## Recommendation

A thin layer of `httpx.AsyncClient`-based route tests (even just smoke-testing that every route in [07-api](../07-api/README.md) returns the expected status code for a valid and an invalid request) would close a real, confirmed gap — several historical bugs in this codebase were route-level wiring issues, not service-logic issues, and would have been caught by exactly this kind of test.
