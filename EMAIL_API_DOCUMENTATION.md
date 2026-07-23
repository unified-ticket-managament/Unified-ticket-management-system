# Email API Documentation

Inspection of every email-related API endpoint in `unified-backend`. All paths, models, and auth checks below were read directly from source; nothing was changed to produce this document.

Routers are mounted **unprefixed** in `unified-backend/app/main.py` (lines 143, 149 — `app.include_router(ticketing_email_router)` and `app.include_router(ticketing_mail_integration_router)`, no `prefix=` argument), so each route's full path is exactly what's declared via its router's own `prefix` in the two files below — no `/api/v1` involved (that prefix is RBAC-only, per `main.py:139`).

There are **four** email endpoints total, across two router files:

| # | Method & Path | File | Auth |
|---|---|---|---|
| 1 | `POST /emails/incoming` | `api/email.py` | None (unauthenticated) |
| 2 | `POST /emails/dummy` | `api/email.py` | Bearer token, Site Lead only |
| 3 | `POST /api/mail/outgoing` | `api/mail_integration.py` | Bearer token, any agent role |
| 4 | `POST /api/mail/incoming` | `api/mail_integration.py` | None (unauthenticated) |

There is **no** validation-token endpoint (see §3).

---

## 1. Outgoing email endpoint

### `POST /api/mail/outgoing`
`unified-backend/app/ticketing/api/mail_integration.py`, lines 97–121.

- **Purpose**: accepts a frontend-authored email object and dispatches it through `MailProviderClient` (currently `MockMailProviderClient` only — see `EMAIL_INTEGRATION_ANALYSIS.md`). Deliberately decoupled from ticket/interaction bookkeeping — the existing ticket reply/compose flow does **not** go through this route; it uses the older `OutboundDispatcher` path in `InteractionService` instead.
- **Auth**: `Depends(get_current_agent)` — see §4.
- **Handler flow**: builds an `OutgoingMailService` (injecting `get_mail_provider_client()`), calls `service.send_email(request)`. A `ValueError` (e.g. unknown `client_id`) is translated to `404`.
- **Status code**: `201 Created` on success.
- **Request model**: `OutgoingEmailRequest` (§5).
- **Response model**: `OutgoingEmailResponse` (§6).
- **Note on completeness**: the response message is literally `"Email dispatched successfully (mocked — Microsoft Graph integration pending)."` — this is not a placeholder in the docs, it's the real string the API returns today.
- **No frontend caller exists** for this route anywhere in `unified-frontend/src` (verified by search) — it's callable today only via direct HTTP (Swagger/Postman/curl).

There is no second "outgoing" endpoint for Graph specifically — sending is provider-agnostic by design; there's one route regardless of which `MailProviderClient` implementation is behind it.

---

## 2. Incoming webhook endpoint(s)

Two separate routes accept inbound mail; both converge on the same core service.

### `POST /emails/incoming`
`unified-backend/app/ticketing/api/email.py`, lines 108–153.

- **Purpose**: "the real inbound-email transport route — service-to-service (N8N / the future Graph webhook)" (verbatim docstring, lines 130–134). This is the transport actually in use today, fed by an external N8N workflow.
- **Content type**: `multipart/form-data` — every field is a `Form(...)`/`Form(default=...)` parameter, not a JSON body: `to_email`, `from_email`, `from_name`, `subject`, `body`, `html_body`, `message_id`, `received_at`, `in_reply_to`, `references` (space-separated string, split into a list before validation), `conversation_id`, plus `files: list[UploadFile]` for attachments.
- **Auth**: none — deliberately unauthenticated so an external webhook caller with no user Bearer token can reach it.
- **Handler flow**: constructs an `EmailRequest` from the form fields, builds an `EmailService` (via the module-local `_build_email_service` helper, lines 45–73), calls `service.receive_email(email, files=files)`.
- **Error mapping** (`_receive_email`, lines 76–105): `ValueError("Email already processed.")` → `409`; `ValueError("Unknown inbox address.")` → `404`; any other `ValueError` → `400`.
- **Status code**: `201 Created`.
- **Response model**: `EmailResponse` (§6).

### `POST /api/mail/incoming`
`unified-backend/app/ticketing/api/mail_integration.py`, lines 124–161.

- **Purpose**: "a JSON/Graph-shaped sibling of the existing form-encoded `POST /emails/incoming`... Accepts a realistic Microsoft Graph `message` payload" (verbatim comment, lines 10–16). This is **not** a live Graph webhook receiver — it's a hand-authored JSON shape matching what a real Graph notification-triggered fetch would look like, built to prove out the mapping logic ahead of real Graph credentials existing.
- **Content type**: JSON body, model `IncomingMailPayload` (§5) — no attachment/`files` support (see gap below).
- **Auth**: none — same rationale as `/emails/incoming` ("deliberately unauthenticated, same as `POST /emails/incoming`... this is a service-to-service transport route, not user-facing," lines 135–136).
- **Handler flow**: `map_external_email_to_interaction(payload)` (`services/mail_mapping_service.py`) converts the Graph-shaped payload into an `EmailRequest`, then hands it to a **freshly built, separate** `EmailService` instance (`_build_email_service` is re-declared locally in this file, lines 63–94, not imported from `api/email.py` — the comment at lines 64–70 explains this is deliberate since the other one is module-private, not a divergent implementation).
- **Attachment gap**: the call is `await service.receive_email(email_request)` — no `files` argument is passed, so `EmailService.receive_email`'s `files` parameter (default `None`, per `services/email_service.py` line 101) is never populated on this path. A real Graph message's attachments (which Graph exposes via a separate `GET /messages/{id}/attachments` call, not inline in the message body) are not fetched or stored by this route today.
- **Error mapping**: identical three-way `ValueError` handling as `/emails/incoming` (409/404/400), duplicated inline rather than shared via `_receive_email`.
- **Status code**: `201 Created`.
- **Response model**: `EmailResponse` (§6) — same response shape as the other inbound route, confirming both are meant to be interchangeable from the caller's perspective.

### `POST /emails/dummy` (test/simulator variant, not a real inbound transport)
`unified-backend/app/ticketing/api/email.py`, lines 156–209.

- **Purpose**: "the internal 'Create Dummy Mail' simulator — Site Lead only. Runs through the exact same `EmailService.receive_email`... the only difference is this route requires an authenticated Site Lead instead of being open" (verbatim docstring). Exists so inbound mail can be simulated from the UI/Postman without a real mailbox or N8N.
- **Content type**: same multipart form fields as `/emails/incoming`.
- **Auth**: `Depends(get_current_agent)` plus an explicit in-handler role check against `DUMMY_MAIL_ROLE_NAMES = {"Site Lead"}` (`services/access_control.py` line 77) — returns `403` for any other role (line 187–191).
- Kept as a **separate route** rather than adding role-gating to `/emails/incoming` itself, "since that one must stay reachable without a user Bearer token for the real webhook" (lines 182–184).

---

## 3. Validation token endpoint

**Does not exist.** Verified directly — no route, function, or query parameter named `validationToken` (or similar) exists anywhere in the repo.

Microsoft Graph's real webhook-subscription lifecycle requires a receiving endpoint to:
1. Echo back a `validationToken` query parameter as plain text, synchronously, when Graph first validates a new subscription's notification URL.
2. Verify a caller-chosen `clientState` value on every subsequent change notification, to reject forged/unauthenticated pushes.

Neither exists. The closest thing to an acknowledgment of this gap is the docstring on `POST /api/mail/incoming` itself (`api/mail_integration.py`, lines 138–144):

> "NOTE: a real Microsoft Graph webhook subscription requires validating a `validationToken` query param on the subscription handshake (echoed back as plain text) and checking `clientState` on every notification. **Neither is implemented yet** — this route only demonstrates accepting and mapping a Graph-shaped message body; don't point a live Graph subscription at it until that validation is added."

There is also no endpoint for **creating or renewing** a Graph subscription (`POST /subscriptions` against Graph itself, called from this backend) — that's a separate, equally-missing piece (see `EMAIL_INTEGRATION_CHECKLIST.md`'s "Inbound receive" section).

---

## 4. Authentication middleware

There's no email-specific middleware — all four routes rely on the same shared FastAPI dependency-injection auth used everywhere else in `app.ticketing`, defined in `unified-backend/app/dependencies/auth.py`:

| Dependency | Used by | Behavior |
|---|---|---|
| *(none)* | `POST /emails/incoming`, `POST /api/mail/incoming` | No `Depends` at all — open routes, by design, for service-to-service webhook delivery |
| `get_current_user` | (indirectly, via `get_current_agent` below) | Decodes the JWT (`decode_token`), checks `type == "access"`, resolves the user either from an in-memory RBAC cache hit (`_build_transient_user`, zero DB round trips) or a fresh DB lookup on a cache miss/version mismatch (see `unified-backend/CLAUDE.md`'s "Cross-service identity" section for the full cache design) |
| `get_current_agent` | `POST /api/mail/outgoing`, `POST /emails/dummy` | Wraps `get_current_user`, then additionally requires `current_user.role.name` to be in `AGENT_ROLE_NAMES` (`access_control.py`) — i.e., any role that can act on tickets, rejecting only RBAC's client-facing "Viewer" role with `403` |
| In-handler role check | `POST /emails/dummy` only | After `get_current_agent` passes, an explicit `if current_user.role.name not in DUMMY_MAIL_ROLE_NAMES` check further narrows this one route to Site Lead only (`403` otherwise) — `get_current_agent` alone isn't strict enough for this route |

**No Graph-specific authentication exists** — no MSAL token validation, no Azure AD JWT verification, no `clientState` check. The two unauthenticated routes trust the caller purely by network/deployment topology (whatever's calling them is assumed to be N8N or a trusted internal service), which is exactly why the `validationToken`/`clientState` gap in §3 matters before ever pointing a real Graph subscription at `/api/mail/incoming`.

---

## 5. Request models

All in `unified-backend/app/ticketing/schemas/`.

### `EmailRequest` (`schemas/email.py`, lines 8–67) — used by `/emails/incoming` and `/emails/dummy`
| Field | Type | Required | Notes |
|---|---|---|---|
| `to_email` | `EmailStr` | Yes | The shared inbox address — resolves the `Client`, not `from_email` |
| `from_email` | `EmailStr` | Yes | Sender's address, stored as contact info only |
| `from_name` | `str \| None` | No | max 255 |
| `subject` | `str` | Yes | 1–255 chars |
| `body` | `str` | Yes | min 1 char |
| `html_body` | `str \| None` | No | |
| `message_id` | `str` | Yes | 1–255 chars; the dedupe key |
| `received_at` | `datetime \| None` | No | Defaults to "now" in the service if omitted |
| `in_reply_to` | `str \| None` | No | max 255; RFC 5322 threading header |
| `references` | `list[str]` | No | defaults to `[]`; RFC 5322 threading header |
| `conversation_id` | `str \| None` | No | max 255 — "Microsoft Graph's own conversation identifier — unavailable until Task 1 ships; accepted now (optional) so this schema doesn't need to change again once it does" (verbatim comment, lines 63–66) |

### `IncomingMailPayload` (`schemas/mail_integration.py`, lines 63–115) — used by `POST /api/mail/incoming`
A near-literal mirror of Microsoft Graph's `message` resource:
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `str \| None` | No | Graph's own message id, distinct from `internetMessageId` |
| `internetMessageId` | `str` | Yes | min 1 — maps to `EmailRequest.message_id` |
| `subject` | `str` | No | default `""`, max 255 |
| `from_` (aliased `from`) | `GraphRecipient` | Yes | `populate_by_name=True` set on the model config |
| `toRecipients` | `list[GraphRecipient]` | Yes | min 1 item; `toRecipients[0]` is treated as the shared inbox address |
| `ccRecipients` | `list[GraphRecipient]` | No | default `[]` |
| `body` | `GraphItemBody` | Yes | `{contentType: "text"|"html", content: str}` |
| `conversationId` | `str \| None` | No | "highest-priority thread-match signal" |
| `receivedDateTime` | `datetime \| None` | No | |
| `internetMessageHeaders` | `list[GraphInternetMessageHeader] \| None` | No | Only present when fetched with `$select=internetMessageHeaders`; this is where `In-Reply-To`/`References` are pulled from |

Nested models: `GraphEmailAddress {name, address}`, `GraphRecipient {emailAddress}`, `GraphItemBody {contentType, content}`, `GraphInternetMessageHeader {name, value}` — all in the same file.

### `OutgoingEmailRequest` (`schemas/mail_integration.py`, lines 123–157) — used by `POST /api/mail/outgoing`
| Field | Type | Required | Notes |
|---|---|---|---|
| `client_id` | `UUID \| None` | Conditionally | Send From this client's shared inbox; mutually exclusive with `from_email` |
| `from_email` | `EmailStr \| None` | Conditionally | Explicit From address, only used when `client_id` is omitted |
| `from_name` | `str \| None` | No | max 255 |
| `to_email` | `EmailStr` | Yes | |
| `cc` | `list[EmailStr]` | No | default `[]` |
| `bcc` | `list[EmailStr]` | No | default `[]` |
| `subject` | `str` | Yes | 1–500 chars |
| `body` | `str` | Yes | 1–20000 chars |

A `model_validator(mode="after")` (`_require_a_sender`) enforces that at least one of `client_id`/`from_email` is set — raises a plain `ValueError`, which FastAPI/Pydantic surfaces as a `422` before the route body ever runs. **No attachment field exists on this model.**

---

## 6. Response models

### `EmailResponse` (`schemas/email.py`, lines 70–95) — returned by both inbound routes
| Field | Type | Notes |
|---|---|---|
| `message` | `str` | |
| `interaction_id` | `str` | |
| `client_id` | `str` | |
| `client_name` | `str` | |
| `ticket_id` | `str \| None` | Set only when header-matching landed the email directly on an existing ticket |
| `threaded_under` | `str \| None` | Set whenever a thread root was found, independent of whether it's ticketed yet |
| `status` | `str` | |
| `attachments` | `list[AttachmentMetadata]` | default `[]` |

### `OutgoingEmailResponse` (`schemas/mail_integration.py`, lines 160–167) — returned by `POST /api/mail/outgoing`
| Field | Type | Notes |
|---|---|---|
| `message` | `str` | Today always `"Email dispatched successfully (mocked — Microsoft Graph integration pending)."` |
| `provider_message_id` | `str` | Today always `f"mock-{uuid4().hex}"` (`MockMailProviderClient`) |
| `status` | `str` | Today always `"SENT"` |
| `dispatched_at` | `datetime` | `datetime.now(timezone.utc)` at response-build time |
| `envelope` | `OutboundEnvelope` | The envelope actually built and handed to the provider client (`schemas/payloads.py`) |

### `MailProviderSendResult` (`services/mail_provider.py`, lines 19–21) — internal, not exposed directly on any route, but feeds `OutgoingEmailResponse`
`{provider_message_id: str, status: str}`.

---

## Summary: what's real vs. what's scaffolding

| Endpoint | Actually functional today? | Talks to Graph? |
|---|---|---|
| `POST /emails/incoming` | Yes — production inbound path via N8N | No |
| `POST /emails/dummy` | Yes — internal test simulator | No |
| `POST /api/mail/outgoing` | Yes, but only against the mock provider; no real send happens | No |
| `POST /api/mail/incoming` | Yes, but only as a mapping-logic demo; no real Graph subscription feeds it, and no validation exists to safely accept one if it did | No |
| *(subscription create/renew)* | Does not exist | N/A |
| *(validation token handshake)* | Does not exist | N/A |

This matches `EMAIL_INTEGRATION_ANALYSIS.md`'s conclusion: every endpoint above is either a real, working non-Graph transport, or a deliberately-mocked seam built ahead of Graph credentials — none of them constitute a working Microsoft Graph integration yet.
