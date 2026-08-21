# Notifications API

Source: `app/notifications/routes.py` (prefix `/notifications`). Service: `NotificationService` (`app/notifications/service.py`) — the single write path (`notify()`) every trigger across `app.rbac` and `app.ticketing` calls through (~17 call sites). See [03-business-workflows/notification/notification-workflow.md](../03-business-workflows/notification/notification-workflow.md).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/notifications` | List caller's notifications (paginated, `unread_only`, `types` filter) | `get_current_user` |
| GET | `/notifications/stream` | Server-Sent Events stream of new notifications | `get_current_user_sse` — token via `?token=` query param, not header |
| POST | `/notifications/{id}/read` | Mark one notification read | `get_current_user` |
| POST | `/notifications/read-all` | Mark all read | `get_current_user` |
| POST | `/notifications/clear-all` | Soft-delete/dismiss all notifications | `get_current_user` |

## SSE stream details

- Format: `event: notification` lines, JSON `data:` payload `{"notification": {...}, "unread_count": <int>}`, plus a `: heartbeat` comment every 25s (keeps proxies from killing an idle connection, and doubles as this generator's own disconnect check via `request.is_disconnected()`).
- Keyed per `user_id`, fanning out to a `set[asyncio.Queue]` — one queue per open tab/device, so multiple simultaneously-open tabs each get an independent copy of every event.
- `get_current_user_sse` opens its own short-lived DB session (not the request-scoped one `Depends(get_db)` would hold for the connection's entire lifetime — potentially hours) purely for the one-time, usually cache-hit auth check.
- Per-process, in-memory only (`NotificationStreamManager`) — no cross-process broadcast. See [16-known-limitations/technical-limitations.md](../16-known-limitations/technical-limitations.md).

## Business logic

- `notify()` dedups recipients before creating any rows — one call can never produce two rows (or two emails) for the same recipient.
- Business-critical types (`TICKET_ASSIGNED`, `ESCALATION_CREATED`, `SLA_BREACHED`, `CLIENT_REPLY`, `EDIT_ACCESS_APPROVED`, `EDIT_ACCESS_REJECTED`) additionally queue a real outbound email via a fire-and-forget background task (`email_notifier.queue_notification_emails`), governed by one frozenset (`EMAIL_ELIGIBLE_NOTIFICATION_TYPES`, `app/notifications/email_policy.py`) — the only place this policy needs editing.
- Every notification also publishes to the SSE stream (`manager.publish`) immediately, skipped cheaply if the recipient has no open connection.
