# Notification Management Module

## Purpose
Deliver a consistent in-app + (for a fixed set of types) email notification for every significant event, through one write path, in real time.

## Responsibilities
- `notify()` — the single write path for all ~17 call sites across both domains.
- Real-time delivery via Server-Sent Events.
- Conditional outbound email for business-critical types.

## Main Components
- `app/notifications/{service,repository,sse_manager,email_notifier,email_content,email_policy,routes,models,schemas}.py`

## Inputs
Any triggering event across `app.rbac`/`app.ticketing`.

## Outputs
`notifications` rows; SSE push events; queued outbound emails.

## Business Rules
- `notify()` dedupes recipients before writing — one call can never produce two rows for the same recipient.
- Email eligibility is governed by exactly one frozenset (`EMAIL_ELIGIBLE_NOTIFICATION_TYPES`) — editing that set is the only change needed to add/remove a type from email delivery.
- SSE publish and email dispatch are both wrapped in never-raise error handling — neither can fail the already-durable notification write.
- Deactivated users are never emailed.

## Dependencies
`UserRepository` (recipient email resolution), `email_sender.py` (SMTP transport), deferred import of ticketing models for ticket-context enrichment.

## Database Entities
`notifications`.

## APIs
[07-api/notifications.md](../07-api/notifications.md).

## Important Classes/Services
`NotificationService`, `NotificationStreamManager`.

## External Integrations
SMTP (or logging-only fallback).

## Known Limitations
- Per-process, in-memory only — no multi-worker broadcast (see [16-known-limitations/technical-limitations.md](../16-known-limitations/technical-limitations.md)).
- Outbound business-critical email is confirmed only via unit tests, not a live SMTP/production check, per root `CLAUDE.md`'s own caveat.
- This documentation pass found two different descriptions of the exact `EMAIL_ELIGIBLE_NOTIFICATION_TYPES` membership across sources (a 6-member and a 3-member version) — verify directly against `app/notifications/email_policy.py` before relying on the exact list for an operational decision.

## Related workflows
[03-business-workflows/notification/notification-workflow.md](../../03-business-workflows/notification/notification-workflow.md).
