# Using Swagger / OpenAPI

With the backend running locally:

- **Swagger UI**: `http://localhost:8000/docs` — interactive, lets you authenticate (via the login endpoint's response) and try any endpoint directly.
- **ReDoc**: `http://localhost:8000/redoc` — a read-only, more polished reference view of the same schema.
- **Raw schema**: `http://localhost:8000/openapi.json`.

## Why this matters more than usual for this project

This is the **live, always-current** source of truth for the API surface — more reliable than any static documentation (including [07-api](../07-api/README.md) in this very docs tree, which is a snapshot as of this documentation pass). If a route's exact request/response shape ever seems to disagree with what's written in [07-api](../07-api/README.md), trust `/docs` against the running code.

## A practical workflow this project's own history recommends

Root `CLAUDE.md` repeatedly documents using a real minted token plus a direct `httpx`/`curl` call against the actual route (not just the underlying service method) as the most reliable way to confirm a fix is genuinely live — Swagger UI's "Try it out" feature is the interactive equivalent of this same practice, and is the fastest way to do it without writing a script.

## Two domains, one schema

Since `unified-backend` serves both RBAC (`/api/v1/...`) and Ticketing (unprefixed) from one FastAPI app, `/docs` shows both domains' routes together, grouped by their router tags — a convenient way to see the entire API surface in one place without cross-referencing two separate services' documentation, unlike in the pre-consolidation architecture.
