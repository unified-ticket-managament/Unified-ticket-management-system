# Communication & Notification Tables

## `mail_folders`

`folder_id` (PK), `name` (String(100), UNIQUE — global, not per-user), `created_by` (FK→users), `created_at`.

## `rules` (Mail Rules and OTP Rules — one generic table)

| Column | Type | Business meaning |
|---|---|---|
| rule_id | PK | |
| name | String | |
| category | String(20), indexed | `mail_rule` / `otp_rule` — a plain string, deliberately not a DB enum since this vocabulary is expected to grow without a migration |
| is_enabled | Boolean | |
| conditions | JSONB | Condition tree (field/operator/value, combinator AND/OR) |
| exceptions | JSONB, default `{"combinator":"AND","rules":[]}` | |
| actions | JSONB list | e.g. forward-to-employees |
| stop_processing | Boolean | Mirrors Outlook's own rule semantics |
| priority | Integer | Dense, per-category ordering |
| created_by | FK→users | |
| created_at / updated_at | | |

A rule's `client` condition, if present, is an **exact-match filter** — see [04-functional-modules/communication-management.md](../../04-functional-modules/communication-management.md).

## `message_read_receipts`

Composite PK `(user_id, interaction_id)`, both FK, `read_at`.

## `notifications`

| Column | Type | Business meaning |
|---|---|---|
| notification_id | PK | |
| user_id | FK→users, indexed, NOT NULL | Recipient |
| notification_type | String(50), indexed | Plain string, not a DB enum (`NotificationType` is a Python string-constant class) |
| title / message | String(255) / Text | |
| link | String(500), null | Frontend route — written as if the ticket workspace were mounted at the app root; the frontend's `resolveNotificationHref()` adds the `/dashboard` prefix where needed |
| related_entity_type | String(50), null | Free-form, not enum-constrained |
| related_entity_id | UUID, no FK | Polymorphic per `related_entity_type` |
| is_read | Boolean, default False, indexed | |
| created_at | indexed | |
| dismissed_at | nullable | Soft-delete for "Clear All" |
