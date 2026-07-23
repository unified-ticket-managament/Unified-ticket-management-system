# Incoming Email Webhook — Implementation Review

Full trace of `unified-backend`'s inbound-email handling, covering the seven areas requested. No code was changed to produce this document. As with the last several reports, a few of the requested concepts (validation token handling, a lightweight "notification" payload, background processing, a separate email-fetch step) describe how a **real Microsoft Graph webhook** works, but don't describe what's actually implemented here — each is called out explicitly below rather than assumed.

Two routes accept inbound mail; both converge on the identical core service, `EmailService.receive_email` (`unified-backend/app/ticketing/services/email_service.py`):

- `POST /emails/incoming` (`api/email.py`) — the real, production transport, form-encoded, fed by an external N8N workflow.
- `POST /api/mail/incoming` (`api/mail_integration.py`) — a JSON body shaped like a Microsoft Graph `message` resource, mapped into the same internal shape via `map_external_email_to_interaction()`, but not connected to any real Graph subscription.

---

## 1. Validation token handling

**Not implemented.** No route, function, or query parameter named `validationToken` exists anywhere in the repo (confirmed by direct search, and already noted in `EMAIL_API_DOCUMENTATION.md` and `GRAPH_AUTHENTICATION.md`).

For context on what's missing: a real Graph webhook subscription requires the receiving endpoint to synchronously echo back a `validationToken` query parameter as plain text the first time Graph validates a new subscription's notification URL, and to check a caller-chosen `clientState` value on every subsequent notification to reject forged pushes. `POST /api/mail/incoming`'s own docstring (`api/mail_integration.py`, lines 138–144) states this directly:

> "a real Microsoft Graph webhook subscription requires validating a `validationToken` query param on the subscription handshake (echoed back as plain text) and checking `clientState` on every notification. Neither is implemented yet — this route only demonstrates accepting and mapping a Graph-shaped message body; don't point a live Graph subscription at it until that validation is added."

Neither `POST /emails/incoming` nor `POST /api/mail/incoming` has any request-authenticity check at all — both are wide open, deliberately, and rely entirely on network/deployment topology (only a trusted N8N workflow or internal caller is expected to reach them) rather than any cryptographic or token-based verification.

## 2. Notification payload

There is no "notification" in the Graph sense — a lightweight ping saying "something changed, go fetch it." Both routes instead receive **the full email content directly in the request body**:

- `POST /emails/incoming` — `multipart/form-data`, one field per piece of data: `to_email`, `from_email`, `from_name`, `subject`, `body`, `html_body`, `message_id`, `received_at`, `in_reply_to`, `references` (space-separated, split before validation), `conversation_id`, plus `files: list[UploadFile]` for attachments inline in the same request.
- `POST /api/mail/incoming` — a JSON body matching `IncomingMailPayload` (`schemas/mail_integration.py`), a near-literal mirror of Graph's `message` resource: `internetMessageId`, `subject`, `from` (aliased, `GraphRecipient`), `toRecipients`/`ccRecipients` (`list[GraphRecipient]`), `body` (`GraphItemBody` — `contentType`/`content`), `conversationId`, `receivedDateTime`, and optionally `internetMessageHeaders` (only present when the real Graph API is queried with `$select=internetMessageHeaders` — this schema accepts the field but nothing in this codebase actually issues that Graph query, since no Graph client exists).

So what's called the "notification payload" here is really the **entire resolved message**, not Graph's actual two-step "notification then fetch" model — see §4.

## 3. Background processing

**Not implemented — everything runs synchronously, inline, inside the HTTP request/response cycle.** A repo-wide search for `BackgroundTasks`, `asyncio.create_task`, Celery, or any task queue inside `app/ticketing` returned zero matches. `EmailService.receive_email` performs all of the following before the route ever returns its `201` response, in order, awaited one after another on the same request:

1. Duplicate check (one query)
2. Client lookup (one query, plus a defensive Account-Manager-validity check — a second query)
3. Thread-match lookups (up to three sequential queries: `conversation_id`, then `in_reply_to`, then `references`, short-circuiting on the first hit)
4. `find_thread_root` (a recursive query) if a match was found
5. `InteractionCreate` insert
6. SLA clock start/resume (`SLAService`)
7. Audit log write
8. Notification fan-out (`NotificationService.notify`, including further lookups for global-inbox role users or the assigned agent's Team Lead)
9. Attachment validation + storage upload, if `files` were provided

A slow storage backend, a slow SLA calculation, or a notification fan-out to many recipients all directly add to this one request's latency — there's no fire-and-forget step, and no retry queue if any of steps 6–9 fails after the interaction itself is already committed (see §7 for how errors are actually surfaced).

## 4. Email fetching

**No separate "fetch the full message" step exists — because none is needed with the current design.** In a real Graph integration, a webhook notification only carries a message `id` and minimal metadata; the receiver must make a follow-up `GET /users/{mailbox}/messages/{id}` call (with the app's own Graph access token) to retrieve the actual subject/body/headers before it can do anything useful. That two-step "notified, then fetch" pattern does not exist here, for the simple reason that both current routes already receive the complete message content in the initial request (§2) — there is nothing left to go fetch.

This is also why `POST /api/mail/incoming`'s docstring is careful to say it "only demonstrates accepting and mapping a Graph-shaped message body" — a real Graph subscription would never hand this route a fully-populated message like this up front; something would first need to receive the lightweight notification and perform the missing fetch call, and that piece doesn't exist.

## 5. Attachment download

There is no "download" step either — for the same reason as §4. Attachments arrive as **direct file uploads in the same multipart request**, not as references to be separately downloaded from a provider:

- `POST /emails/incoming` accepts `files: list[UploadFile]` directly in its form body. `EmailService.receive_email` passes these straight to `AttachmentService.validate_and_store_files(files, created.interaction_id)` (`email_service.py`, lines 400–408) — only if `files` is non-empty; attachments are optional.
- `validate_and_store_files` (`services/attachment_service.py`, lines 147+) enforces: a max file count (`MAX_ATTACHMENT_FILES`), filename sanitization (`sanitize_filename`), content-type/extension validation (`validate_attachment_type`, `415` on failure), a 25MB per-file size cap (`413` on failure), then uploads the raw bytes to the configured storage backend (`storage_service.upload`, Supabase or S3-compatible depending on `STORAGE_BACKEND`) under a generated object key, and creates an `Attachment` DB row.
- **`POST /api/mail/incoming` has no attachment path at all.** `receive_incoming_email` (`api/mail_integration.py`) calls `service.receive_email(email_request)` with no `files` argument — `receive_email`'s `files` parameter defaults to `None`, so this branch is simply never entered. A real Graph message's attachments (which Graph itself exposes only via a separate `GET /messages/{id}/attachments` call, never inline in the message JSON) would need their own fetch-and-store implementation that doesn't exist yet — this gap is also called out in `EMAIL_INTEGRATION_CHECKLIST.md`.

## 6. Interaction creation

The core of `EmailService.receive_email` (after duplicate/client checks pass):

1. **Thread resolution** — checked in strict priority order, first match wins (no merging across tiers): `conversation_id` (via `get_by_conversation_id`) → `in_reply_to` (via `get_by_message_ids`) → `references` (same lookup, list of candidates). "We don't merge candidates from lower tiers once a higher one matches, so a `conversation_id` match can't be second-guessed by an unrelated References entry."
2. If a match is found, `find_thread_root` (a recursive resolve, not a single hop) locates the true thread root so every reply in a conversation points at the same root rather than chaining. If the matched interaction already belongs to a ticket, this new email is attached to that `ticket_id` directly and marked `InteractionStatus.ASSIGNED`; otherwise it stays `PENDING` (a still-untracked inbox item).
3. An `InteractionCreate` is built: `interaction_type="EMAIL"`, `direction=INBOUND`, `performed_by=None` ("no authenticated user exists yet — the email has only been received"), full email content in `payload`, plus first-class columns `message_id`, `client_id`, `parent_interaction_id`, `received_at`, `conversation_id`, `in_reply_to_message_id`, `references`, `subject`.
4. **SLA clock**: a genuinely new thread root (no match at all) starts a First Response clock; a reply landing directly on an existing ticket instead resumes that ticket's Resolution clock if it had been paused — deliberately mutually exclusive, "to avoid double-clocking the same conversation."
5. **Audit log**: `EMAIL_RECEIVED`, actor recorded as `ActorRole.CLIENT` (`actor_id=None`, `actor_name` = the sender's name or address) — the client is the actor here, there's no agent to attribute it to.
6. **Notifications**: two distinct audiences depending on whether the email landed on an existing ticket — a brand-new pending item notifies the client's Account Manager plus every Site Lead/Super Admin (global inbox); a reply on an already-ticketed thread instead notifies only that ticket's assigned agent and their Team Lead (deliberately not fanned out further, "every single client reply would flood [Site Lead/Super Admin's] bell at any real ticket volume").
7. **Attachments**, if any were sent in the same request (§5).
8. Returns `EmailResponse` — `interaction_id`, `client_id`/`client_name`, `ticket_id` (set only if this landed directly on a ticket), `threaded_under` (set whenever a thread root was found, independent of ticketing), `status`, and `attachments`.

## 7. Duplicate detection

A single check, first thing in `receive_email` (lines 104–116): `InteractionRepository.exists_by_message_id(email.message_id)`. If a row with that `message_id` already exists, the method raises `ValueError("Email already processed.")` **before** any client lookup, thread matching, SLA work, or attachment storage happens — the entire rest of the pipeline is skipped.

Both route handlers translate this specific `ValueError` message into an HTTP `409 Conflict` (`_receive_email` in `api/email.py`, and the equivalent inline `if message == "Email already processed."` check in `api/mail_integration.py`'s `receive_incoming_email`) — a caller retrying a delivery (a common webhook behavior, since providers often redeliver on an ambiguous/timeout response) gets a clear, idempotent-safe rejection rather than a duplicate `Interaction` row or a duplicated notification/SLA-clock start.

This is the **only** duplicate-safety mechanism in the pipeline — it relies entirely on the sending system supplying a stable, unique `message_id` (RFC 5322 Message-ID for the real transport; `internetMessageId` for the Graph-shaped route) on every delivery, including redeliveries of the same message. There is no secondary idempotency key (e.g. a provider-specific delivery/notification ID) and no deduplication window — a message with a genuinely different `message_id` but identical content would not be caught.

---

## Summary against what was asked to verify

| Item | Status |
|---|---|
| Validation token handling | Not implemented — no route or check exists |
| Notification payload | N/A as Graph defines it — both routes receive the full message directly, not a lightweight ping |
| Background processing | Not implemented — fully synchronous within the request |
| Email fetching | Not implemented — nothing to fetch, since the full message already arrives in the request |
| Attachment download | Not implemented as a "download" — attachments arrive as direct uploads on `/emails/incoming` only; `/api/mail/incoming` has no attachment handling at all |
| Interaction creation | Fully implemented and working — dedupe, client resolution, threading, ticket-linking, SLA clock, audit log, notifications, response |
| Duplicate detection | Fully implemented — a single `message_id` existence check, first step in the pipeline, mapped to `409` |

Net: the parts of this flow that are genuinely about *this platform's own data model* (interaction creation, threading, duplicate detection) are complete and in production use. The parts that are specifically *Graph-webhook-shaped* (validation handshake, lightweight notifications, a fetch step, provider-side attachment download) don't exist, because this pipeline was built to receive a fully-resolved message directly rather than to consume a real Graph subscription.
