# Mail Reminders ("Remind me")

A personal, Outlook-style reminder on a mail thread. A user picks a future time; when it comes due UTMS
sends that user (only) a `MAIL_REMINDER_DUE` notification that opens the original email, where they can
snooze or dismiss it.

## How it works

| Concern | Implementation |
|---|---|
| Ownership | `current_user` + **thread-root** `interactions.interaction_id`. `user_id` is taken from the auth token, never the request. |
| Storage | `mail_reminders` (ticketing Alembic chain, revision `0c6db321ee79`, chained after the multi-head merge `444b9869dc1b`). |
| One active per email | Partial unique index `uq_mail_reminders_active_user_interaction (user_id, interaction_id) WHERE status='ACTIVE'`. |
| Time | `remind_at` is a UTC `timestamptz`. The browser sends an ISO instant with an offset; naive datetimes are rejected. Range: strictly future, at most 1 year ahead. |
| Statuses | `ACTIVE` → `FIRED` → `DISMISSED`; `ACTIVE`/`FIRED` → `CANCELED`; `FIRED` → `ACTIVE` (snooze, same row, `snooze_count + 1`). |
| Access | Creating a reminder runs the same view check as opening the email (`BulkMailActionService._ensure_can_view`, which mirrors `OpenEmailService`). An inaccessible/hidden/missing email is a 404. |
| Firing | `app/core/mail_reminder_scheduler.py` (APScheduler, 30 s). Each due row is claimed with `FOR UPDATE SKIP LOCKED`; the `NotificationService.notify()` insert and `ACTIVE → FIRED` commit in one transaction. A failure rolls both back, the row stays `ACTIVE` and is retried next tick. Overdue rows (downtime) are still picked up. |
| Notification | Existing system. Type `MAIL_REMINDER_DUE`, link `/inbox?interaction_id=<root>`, `related_entity_type="interaction"`. Title `Mail Reminder`, message `Reminder: <subject>` (no body). Not email-eligible. |
| Local safety | The scheduler only runs when `APP_ENV=production` unless `MAIL_REMINDER_SCHEDULER_ENABLED` is set explicitly (`true`/`false`). Interval: `MAIL_REMINDER_SWEEP_INTERVAL_SECONDS` (default 30). |

> **Deployment note:** a host that doesn't set `APP_ENV=production` (e.g. the EC2 systemd service) must set
> `MAIL_REMINDER_SCHEDULER_ENABLED=true`, or it will never fire reminders. Render already sets `APP_ENV=production`.

## API (`/mail-reminders`, any authenticated agent)

| Method | Path | Body | Result |
|---|---|---|---|
| POST | `/mail-reminders` | `{interaction_id, remind_at}` | 201 reminder · 404 email missing/inaccessible · 409 active exists · 422 bad time |
| GET | `/mail-reminders?status=&interaction_id=` | | own reminders |
| GET | `/mail-reminders/{id}` | | reminder · 404 |
| PATCH | `/mail-reminders/{id}` | `{remind_at}` | only `ACTIVE` (else 409) |
| DELETE | `/mail-reminders/{id}` | | 204, status `CANCELED` |
| POST | `/mail-reminders/{id}/snooze` | `{remind_at}` **or** `{minutes}` | `ACTIVE` again (409 if closed) |
| POST | `/mail-reminders/{id}/dismiss` | | only `FIRED` (else 409) |

Another user's reminder is always **404** (indistinguishable from a missing one).

## Frontend

* `MailReminderProvider` (mounted in `InboxPage`) owns state (`useMailReminders`) and the single `RemindMeDialog`.
* **Remind me** appears in: the row ⋮ menu, the right-click menu, and the reading-pane toolbar (panel and window).
  Not shown for synthetic rows (`otp-forward:`, compose drafts). No bulk reminders in V1.
* Indicators: bell on the list row (blue = scheduled, amber = due); header chip `Reminder: <time> [Edit] [Remove]`;
  when due, a banner `Reminder due [Snooze] [Dismiss]`.
* Clicking the bell notification uses the existing `/inbox?interaction_id=` deep link.

## Automated tests

Backend (`unified-backend/tests/`): `test_mail_reminder_service.py` (rules, ownership, lifecycle),
`test_mail_reminder_sweep.py` (claiming / atomicity / downtime), `test_mail_reminder_api.py` (HTTP),
`test_mail_reminder_scheduler.py` (lifecycle, flag, notification regression),
`test_mail_reminder_migration.py` (revision graph, offline SQL, model parity),
`test_mail_reminder_db.py` (real PostgreSQL: unique index, SKIP LOCKED across two sessions, failure rollback —
**skips until the migration is applied to the target database**).

Frontend (`unified-frontend/src/`): `ticket-workspace/lib/reminderPresets.test.ts`, `api/__tests__/mailReminders.test.ts`,
`hooks/__tests__/useMailReminders.test.tsx`, `components/mail/__tests__/{RemindMeDialog,MailReminders.ui,
MessageContextMenu.reminder,MessageDetailsView.reminder}.test.tsx`, `pages/__tests__/InboxPage.reminderDeepLink.test.tsx`,
`components/layout/__tests__/top-navbar.mailReminder.test.tsx`.

## Test matrix

| ID | Scenario | Covered by |
|---|---|---|
| R-001 | Create valid reminder | service `test_create_valid_reminder`; api `test_create_returns_201_and_reminder` |
| R-002 | Past / current time rejected | service `…rejects_past_and_current_time`; api `test_past_datetime_is_422` |
| R-003 | Another user's reminder → 404 (get/patch/delete/snooze/dismiss) | service + api `…is_404_on_every_route`; db `…isolated_per_user` |
| R-004 | Remind me dialog opens | `RemindMeDialog.test` `opens with the title and the quick options` |
| R-005 | Reminder fires | sweep `test_due_reminder_fires_once…`; db `test_due_reminder_creates_one_notification…` |
| R-006 | Notification opens the correct email | `top-navbar.mailReminder` click test; `InboxPage.reminderDeepLink` |
| R-007 | Naive datetime | service/api |
| R-008 | Timezone → UTC instant | service `test_offset_datetime_is_stored_as_utc_instant`; db round trip; presets (local) |
| R-009 | Max horizon (1 year) | service; `reminderPresets`; dialog |
| R-010 | Missing interaction | service; api |
| R-011 | Inaccessible email | service; api |
| R-012 | Reply resolves to thread root | service |
| R-013 | Duplicate active reminder → 409 | service; api; db unique index |
| R-014 | Different users, same email | service; db |
| R-015 / R-016 | Edit / invalid edit | service; api; `MailReminders.ui` edit |
| R-017 | Cancel | service; api; ui Remove |
| R-018 / R-019 | Snooze / invalid snooze | service; api; ui banner |
| R-020 | Dismiss | service; api; ui banner |
| R-021 | List only own | service; api; db |
| R-022 | Authentication required | api (no / invalid token on every route) |
| R-023 | `user_id` in body ignored | api `test_user_id_in_body_is_ignored`; api-client test |
| R-024 | Sweep twice → one notification | sweep; db |
| R-025 | Concurrent sweeps | sweep (lock model); db `test_skip_locked_…` (real PostgreSQL) |
| R-026 | Notification failure → stays ACTIVE, retried | sweep; db |
| R-027 | Downtime recovery | sweep `test_overdue_reminder_fires_after_downtime` |
| R-028 / R-029 | Hidden email / inactive user | sweep; db |
| R-030 | Canceled not fired | sweep; db |
| R-031 | Snoozed fires at new time | sweep; db |
| R-032 | Deleted interaction | sweep (cascade FK in migration SQL test) |
| R-033 | Notification fields | sweep; db |
| R-034 | Existing notifications unchanged | `test_mail_reminder_scheduler` type-set test; navbar "does not disturb others" |
| R-035 / R-036 | SSE / offline delivery | `top-navbar.mailReminder` (stream + list-on-mount) |
| R-037 | Migration | `test_mail_reminder_migration` (graph, up/down SQL, model parity); manual up/down/up |
| R-038 | Remind me menus | `MailReminders.ui` (⋮), `MessageContextMenu.reminder`, `MessageDetailsView.reminder` |
| R-039 / R-040 | Presets / custom | `reminderPresets`, `RemindMeDialog` |
| R-041 | Indicator | `MailReminders.ui`, `MessageDetailsView.reminder`, hook |
| R-042 / R-043 | Edit-remove / snooze-dismiss UI | `MailReminders.ui` |
| R-044 | API error UI | `RemindMeDialog`, `MailReminders.ui` |
| R-045 | Deep link | `InboxPage.reminderDeepLink` |
| R-046 – R-051 | Reply / attachments / live mail / ticket / SLA / notification regression | existing suites (see regression run); no protected file was modified |
| R-052 | Scheduler lifecycle | `test_mail_reminder_scheduler` |

## Manual E2E checklist

Prerequisites: migration applied; backend started with `MAIL_REMINDER_SCHEDULER_ENABLED=true` (or `APP_ENV=production`).
Two agent accounts (A and B) who can both see a test email.

- **E2E-001 Create** — A opens the email → *Remind me* → **Tomorrow** → *Set reminder*. The toolbar button becomes
  *Edit reminder*, the header shows `Reminder: Tomorrow 9:00 AM`, and the list row shows a blue bell.
- **E2E-002 Fires** — A sets a custom reminder 1–2 minutes ahead. Wait one sweep tick (≤ 30 s past the time). The bell shows
  *Mail Reminder — Reminder: <subject>*. Click it → the same email opens with the **Reminder due** banner.
- **E2E-003 Snooze** — On the banner choose *Snooze → In 1 hour*. The banner becomes the chip with a time ≈ now + 1 h.
  After the original time passes, no second notification arrives.
- **E2E-004 Isolation** — B opens the same email: no chip, no bell, *Remind me* offered. B creates their own reminder
  (allowed). A's `GET /mail-reminders/<A's id>` as B returns 404.
- **E2E-004b Validation** — a past custom time shows *Pick a time in the future.* and Save stays disabled; a second reminder on
  an email that already has one shows the 409 message inline (try from two tabs).
- **E2E-004c Edit / remove / dismiss** — Edit changes the time; Remove clears the chip; a due reminder's *Dismiss* removes the banner.
- **E2E-005 Regression** — Reply, Reply All, Forward (with an attachment), mark read/unread, a new inbound mail appearing live,
  double-click opens the email window (minimize/maximize), create + assign a ticket, an SLA badge/notification, and an existing
  notification (e.g. ticket assigned) still behave exactly as before.
- **E2E-006 Restart** — Create a reminder 1 minute ahead, stop the backend, wait 3 minutes, start it. The reminder fires on the
  first tick and its message says *(this reminder was due earlier)*.
- **E2E-007 Multiple instances** — run two backend processes against the same DB; a due reminder produces exactly one notification.
