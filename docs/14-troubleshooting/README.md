# Troubleshooting

Organized by functional area. Every entry here is either a **confirmed, documented historical incident** (from root `CLAUDE.md`'s own dated engineering log, cross-checked against the current code) or clearly marked as a **potential issue** if it hasn't actually been observed.

- [authentication/](authentication/README.md)
- [email/](email/README.md)
- [tickets/](tickets/README.md)
- [sla/](sla/README.md)
- [escalation/](escalation/README.md)
- [notifications/](notifications/README.md)
- [database/](database/README.md)
- [deployment/](deployment/README.md)

## The two meta-patterns worth knowing before anything else

1. **An unhandled backend 500 looks exactly like a CORS error in the browser.** Confirmed three separate times in this codebase's history. If a previously-working request suddenly "fails due to CORS" with no CORS config change, suspect an unhandled exception first — reproduce the call directly in a throwaway script, bypassing FastAPI/HTTP, to get the real traceback.
2. **A stale schema (migrations not at head) produces symptoms indistinguishable from a logic bug.** Confirmed at least twice. Always check `alembic ... current` against `heads` for both chains before deep-diving into application code.
