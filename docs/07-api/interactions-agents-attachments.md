# Interactions, Agents & Attachments API

## Interactions — `app/ticketing/api/interaction.py` (prefix `/interactions`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/interactions/{id}/thread` | Full conversation thread (Outlook-style) | `get_current_agent` |
| POST | `/interactions/{id}/hide` | Soft-delete an interaction by id alone (ticket-agnostic) | `get_current_agent` |
| POST | `/interactions/{id}/cancel-send` | Cancel a pending outbound send within the Undo window | `get_current_agent` |

`cancel-send` backs the frontend's "Undo Send" affordance — a brief client-side/server-side window after clicking Send during which the message hasn't actually been dispatched yet.

## Agents — `app/ticketing/api/agent.py` (prefix `/agents`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/agents/assignable` | Who the caller may assign a *new* ticket to (optional `category` filter) | `get_current_agent` |
| GET | `/agents` | List active Staff users (optional `category` filter) | `get_current_user` |

`/agents/assignable` is backed by `AssignmentService.get_assignable_groups` — role-scoped candidate groups (Account Manager → all active Team Leads company-wide + their own reports' Staff; Team Lead → their own category's Staff; Site Lead/Super Admin → everyone active) with a server-side validation step (`resolve_target`) so a crafted `agent_id` can't be assigned outside the caller's actual authority. `/agents` (plain, category-scoped) is the older, simpler picker still used in some UI surfaces (e.g. the Transfer-Agent dialog) that wasn't migrated to the newer service.

## Attachments — `app/ticketing/api/attachment.py` (prefix `/attachments`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/attachments/{id}` | Attachment metadata | `get_current_user` |
| GET | `/attachments/{id}/download` | Redirect to a presigned download URL | `get_current_user` |
| DELETE | `/attachments/{id}` | Delete attachment | `get_current_agent` |

**Historical, fixed critical bug**: `AttachmentService.upload_attachment`'s authorization check used to be called without `await` — the coroutine was created and immediately discarded, silently never running. Any authenticated agent could upload to any ticket regardless of category/client ownership. Fixed during the 2026-07-14/15 RBAC compliance audit.

**Delete permission**: `ticket:archive_attachment`, distinct from `ticket:upload_attachment` (both roles hold upload; archive is Override-only for Team Lead/Staff per the permission matrix).

**Download** is a redirect to a time-limited presigned URL from the configured storage backend (Supabase or S3-compatible) — the backend never proxies the file bytes itself.
