# Production Smoke Tests

**No automated production smoke-test suite exists.** This page is a manual checklist derived from what a real post-deploy verification should cover, given this system's actual architecture — not a description of existing tooling.

## Minimum manual checklist after any production deploy

1. `GET /health` — process liveness.
2. `GET /docs` — confirms the app built its OpenAPI schema (a broken import anywhere would fail this).
3. Log in as a real user via the actual frontend — confirms JWT issuance, CORS configuration, and DB connectivity all work together (a `curl` alone won't catch a CORS misconfiguration a browser would hit).
4. Open the ticket workspace (Staff/Team Lead/Account Manager landing) and confirm tickets load — this round-trips a JWT issued by `app.rbac` through `app.ticketing`'s verification, the single most important cross-domain trust check in the system.
5. Confirm `Scheduled SLA sweep completed` log lines resume on the expected cadence.
6. If Graph is configured: send a real test email to the configured mailbox and confirm it appears in the Inbox within a reasonable window.
7. If SMTP is configured: trigger a business-critical notification (e.g. assign a ticket) and confirm the recipient actually receives an email, not just an in-app notification.

## Why this matters more than usual for this codebase

Several real, historical bugs in this system were only caught by exactly this kind of live, end-to-end check — not by unit tests, which passed throughout. Root `CLAUDE.md`'s own standing convention, repeated across many feature write-ups, is: **"Not yet live-verified against a running backend" is a real, distinct caveat from "unit-tested and type-checked"** — several documented features (business-critical email delivery, the forwarded-mail visibility fix, the Employee ID Create-User gap) were explicitly flagged as needing this exact kind of manual smoke test before being treated as production-proven.

## Recommendation

At minimum, codify steps 1-3 above as a simple post-deploy script (even a shell script calling `curl` against `/health` and `/docs`, plus a scripted login) — closing the gap between "the deploy workflow's health check passed" and "the system is actually usable," which today are not the same guarantee.
