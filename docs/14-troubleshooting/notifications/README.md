# Troubleshooting: Notifications

## Problem: A notification's link 404s when clicked

**Symptoms**: Clicking a bell notification navigates to a URL that 404s in the embedded ticket workspace.

**Possible Causes**: The backend writes every notification `link` as if the ticket workspace were mounted at the app root (`/tickets/{id}`, `/inbox`) — because that's where it lives in the standalone app. In `unified-frontend`, it's mounted under react-router's `basename="/dashboard"` instead.

**How to Diagnose**: Check whether the notification's target path is in `top-navbar.tsx`'s `resolveNotificationHref()` prefix list (`/tickets`, `/inbox`, `/interactions`, `/create-mail`, `/audit-logs`).

**Resolution**: If a *new* notification type's link still 404s, its target path likely needs adding to that prefix list — this was a real, previously-live bug for exactly this reason.

**Related Documentation**: [05-technical-architecture/frontend-architecture.md](../../05-technical-architecture/frontend-architecture.md).

---

## Problem: A business-critical notification's email never arrives

**Symptoms**: An in-app notification (bell/System Mail) appears correctly, but no email follows for a type that should be email-eligible.

**Possible Causes**:
1. `SMTP_HOST` is unset in the current environment — falls back to logging-only, by design.
2. The notification type isn't actually in `EMAIL_ELIGIBLE_NOTIFICATION_TYPES` — verify the exact current membership directly in `app/notifications/email_policy.py` (this documentation pass found two different described memberships across sources and could not fully reconcile them).
3. The recipient's account is `is_active = false` — `get_active_emails_by_ids` deliberately skips inactive users.

**How to Diagnose**: Check backend logs for the fire-and-forget email dispatch task's own log lines; confirm `SMTP_HOST` is actually configured in the environment in question.

**Resolution**: N/A if SMTP is genuinely unconfigured (working as designed). Otherwise, verify the type against the current code.

**Related Documentation**: [04-functional-modules/notification-management.md](../../04-functional-modules/notification-management.md).

---

## Potential Issue: SSE notifications don't arrive for a user connected to a different backend worker process

**Symptoms**: A user with an open `/notifications/stream` connection doesn't receive a real-time push for an event that should target them, but the bell eventually shows it correctly on next poll/reload.

**Possible Causes**: `NotificationStreamManager` is per-process, in-memory — if the backend ever runs as more than one worker process (not the current confirmed topology, but a plausible future scaling step), an event published from one process's `notify()` call never reaches a connection held open on a different process.

**Resolution**: Not applicable to the current single-process deployment. Would require a shared broker (Redis, Postgres `LISTEN/NOTIFY`) if the backend is ever scaled to multiple workers.

**Related Documentation**: [16-known-limitations/technical-limitations.md](../../16-known-limitations/technical-limitations.md).
