# Microsoft Graph Email Integration — Implementation Checklist

Companion to `EMAIL_INTEGRATION_ANALYSIS.md`. That report explains *how* the current code works; this checklist tracks *what's left* to turn the existing mock/N8N seam into a real Microsoft Graph integration. No project code was changed to produce this document.

Legend: `[x]` done today, `[ ]` not started, `[~]` partially done / needs rework.

---

## 1. Completed items

These exist in `unified-backend/app/ticketing/` today and work end-to-end against the mock:

- [x] Provider-agnostic outbound interface — `MailProviderClient` ABC (`services/mail_provider.py`)
- [x] Mock provider implementation — `MockMailProviderClient`, fabricates a `SENT` result, logs the envelope, makes no network call
- [x] Single swap point for a future real client — `get_mail_provider_client()` factory
- [x] Outbound request/response schemas — `OutgoingEmailRequest` / `OutgoingEmailResponse` (`schemas/mail_integration.py`)
- [x] Outbound service layer — `OutgoingMailService.send_email` (`services/outgoing_mail_service.py`), reuses `build_compose_envelope` for the client-shared-inbox invariant
- [x] Outbound route — `POST /api/mail/outgoing` (`api/mail_integration.py`), authenticated agent only
- [x] Graph-shaped inbound schema — `IncomingMailPayload` mirroring Graph's `message` resource (`emailAddress`/`recipient`/`itemBody`/`internetMessageHeaders`) (`schemas/mail_integration.py`)
- [x] Inbound mapping layer — `map_external_email_to_interaction()` converts Graph-shaped JSON into the internal `EmailRequest` (`services/mail_mapping_service.py`), including pulling `In-Reply-To`/`References` out of `internetMessageHeaders`
- [x] Inbound route (Graph-shaped) — `POST /api/mail/incoming` (`api/mail_integration.py`), unauthenticated service-to-service
- [x] Shared core pipeline both transports converge on — `EmailService.receive_email` (`services/email_service.py`): dedupe by `message_id`, client resolution by shared inbox, threading, SLA clock start/resume, `EMAIL_RECEIVED` audit log, in-app notifications
- [x] Existing, already-in-production inbound transport — `POST /emails/incoming` (form-encoded, fed by N8N) plus its authenticated `POST /emails/dummy` test twin (`api/email.py`)
- [x] Unrelated but adjacent working piece: real SMTP send for SLA-breach notification emails (`core/email_sender.py`, `SMTPEmailSender`) — not part of Graph, but the only *real* outbound email path in the repo today

## 2. Missing items

Grouped by area; nothing below exists in the codebase yet.

### Authentication
- [ ] `azure-identity` or `msal` dependency added to `unified-backend/requirements.txt`
- [ ] MSAL client-credentials token acquisition (tenant ID + client ID + client secret → access token)
- [ ] Token caching/refresh logic (Graph app tokens expire; naive per-call acquisition works but should be cached)
- [ ] Secure secret storage decision for the client secret (env var vs. secret manager — not yet decided)

### Outbound send
- [ ] `GraphMailProviderClient` implementing `MailProviderClient`, calling `POST /users/{mailbox}/sendMail`
- [ ] Mapping `OutboundEnvelope` → Graph's `sendMail` request body (to/cc/bcc, HTML vs. text body, reply headers)
- [ ] Attachment support on outbound send (current `OutboundEnvelope`/`OutgoingEmailRequest` have no attachment field at all)
- [ ] Wiring `get_mail_provider_client()` to return the real client behind a config flag (e.g. only when Graph credentials are configured, mirroring how `get_email_sender()` already falls back to logging-only when `smtp_host` is unset)
- [ ] Decision + implementation: unify the older `OutboundDispatcher` (ticket reply/compose path) with the new `MailProviderClient` seam, or explicitly keep them separate long-term
- [ ] Frontend wiring to `POST /api/mail/outgoing` (currently zero callers anywhere in `unified-frontend/src`)

### Inbound receive
- [ ] Graph **change-notification subscription** creation (`POST /subscriptions`) — nothing exists to ask Graph to start notifying this app
- [ ] Subscription **renewal** job (Graph subscriptions expire, max ~3 days for mail — needs a recurring renew, similar in spirit to the existing SLA sweep scheduler)
- [ ] Subscription **`validationToken` handshake** — Graph's subscription-creation handshake requires echoing this back as plain text; `api/mail_integration.py`'s own docstring flags this as unimplemented
- [ ] `clientState` verification on every inbound notification (anti-spoofing check) — explicitly flagged as unimplemented in the same docstring
- [ ] Real Graph change-notification payload handling — Graph notifications are lightweight ("something changed, go fetch it"), not the full message body; a fetch-the-full-message-by-id step (`GET /users/{mailbox}/messages/{id}`) is needed before `map_external_email_to_interaction()` can run, and doesn't exist yet
- [ ] Attachment handling for the Graph-shaped inbound path — `receive_incoming_email` in `api/mail_integration.py` calls `service.receive_email(email_request)` with no `files` argument, so `EmailService.receive_email`'s `files` parameter defaults to `None`; a real Graph message's attachments (fetched separately via `GET /messages/{id}/attachments`) are never retrieved or stored today
- [ ] Decision on whether N8N is retired once Graph webhooks are live, or kept as a fallback/secondary transport

### Configuration
- [ ] New `Settings` fields in `unified-backend/app/core/config.py` (none exist yet): tenant ID, client ID, client secret, target mailbox/shared-inbox UPN(s), webhook `clientState` secret, Graph API base URL/version if not defaulting to `v1.0`
- [ ] `.env.example` / deployment docs updated with the new required variables (see §4 below)

### Observability & resilience
- [ ] Error handling for real Graph API failures (auth failure, throttling, transient 5xx) — the mock never fails, so no failure path has been designed
- [ ] Retry/backoff for Graph's 429 throttling responses
- [ ] Logging/metrics for real send/receive latency and failure rate (current mock logging is a placeholder, not instrumentation)
- [ ] Alerting if subscription renewal fails or a subscription silently expires

## 3. Blocked items

Work that cannot start (or cannot be verified) until an external dependency is resolved:

- [ ] **Everything under "Authentication" above** — blocked on an **Azure AD app registration** existing (tenant ID/client ID/secret). No such registration exists yet per this codebase/config.
- [ ] **Real Graph webhook subscription testing** — blocked on the app having a **publicly reachable HTTPS URL** for `POST /api/mail/incoming` (Graph will not deliver notifications to `localhost`); needs either a deployed environment or a tunneling tool (e.g. ngrok) for local dev.
- [ ] **`sendMail` testing against a real mailbox** — blocked on the Azure AD app being granted `Mail.Send` (application permission, admin-consented) for the target shared mailbox.
- [ ] **Inbound subscription testing** — blocked on the app being granted `Mail.Read` (application permission, admin-consented) for the same mailbox.
- [ ] **Attachment fetch/send** — blocked on the same permission grants above plus deciding attachment size limits (Graph inline vs. large-file upload session behavior).
- [ ] **Deciding N8N's long-term role** — blocked on a product decision (not a technical blocker) about whether Graph webhooks fully replace N8N or run alongside it.
- [ ] **Frontend wiring to `/api/mail/outgoing`** — not technically blocked, but has no assigned owner/epic yet per the codebase's own comments (this seam was "built ahead of" the rest of the work).

## 4. Azure dependencies

Everything below must exist in Azure/Entra ID before any "Missing" item under Authentication/Outbound/Inbound can be implemented against a real mailbox:

- [ ] **Azure AD (Entra ID) tenant** identified/confirmed for this deployment
- [ ] **App registration** created for this application (client ID + tenant ID issued)
- [ ] **Client secret** (or certificate credential) generated for the app registration
- [ ] **API permissions** granted, application (not delegated) type, with admin consent:
  - [ ] `Mail.Send`
  - [ ] `Mail.Read` (or `Mail.ReadWrite` if the integration will mark messages read/move them post-processing)
  - [ ] Consider `Mail.ReadBasic.All` vs. scoping to the specific shared mailbox via application access policy
- [ ] **Application Access Policy** (Exchange Online) scoping the app's mail access to only the intended shared mailbox(es), not every mailbox in the tenant
- [ ] **Shared mailbox** identified (UPN/address) that this integration will send from and receive into
- [ ] **Webhook subscription `clientState` secret** provisioned (app-generated, not Azure-issued, but must be decided/stored alongside the above)
- [ ] Confirmation of **Graph API throttling limits** applicable to the tenant's licensing tier, to size retry/backoff behavior
- [ ] Decision on **certificate vs. client-secret** credential (secret is simpler; certificate is longer-lived and often preferred for production)

## 5. Testing tasks

- [ ] Unit tests for `map_external_email_to_interaction()` against realistic Graph `message` JSON fixtures (including edge cases: missing `internetMessageHeaders`, missing `conversationId`, HTML vs. text body, multiple `toRecipients`)
- [ ] Unit tests for a future `GraphMailProviderClient.send_email` using a mocked Graph HTTP layer (no live network calls in CI)
- [ ] Integration test: full outbound round trip through `POST /api/mail/outgoing` with the real client mocked at the HTTP boundary
- [ ] Integration test: full inbound round trip through `POST /api/mail/incoming` with a realistic Graph payload, asserting the resulting `Interaction`, SLA clock, and notification are all correct (this can reuse most of the existing `EmailService.receive_email` test coverage, since that logic is unchanged)
- [ ] Contract test against Graph's actual API shape periodically (Graph schemas do drift) — at minimum, a manual re-check against Microsoft's published schema when upgrading SDK versions
- [ ] Webhook subscription lifecycle test: create → validate handshake → receive a notification → renew → expire/re-create
- [ ] `clientState` mismatch test — confirm a forged/incorrect `clientState` notification is rejected
- [ ] Throttling/retry test — simulate a 429 from Graph and confirm backoff behaves correctly rather than dropping the message
- [ ] Attachment round-trip test — send an email with an attachment and receive one, once attachment support is built
- [ ] Failure-mode test — Azure AD token acquisition failure (expired/revoked secret) should degrade safely (e.g. fall back to mock/log-only or a clear 5xx) rather than crash the whole request path, mirroring the existing `get_email_sender()` fallback pattern
- [ ] End-to-end manual test against a real (non-production) shared mailbox before go-live: send one email out via `/api/mail/outgoing`, receive it back as a reply via the webhook, confirm the ticket thread is correct
- [ ] Regression test: confirm the existing N8N-fed `POST /emails/incoming` path still works unchanged after any shared-code changes (`EmailService.receive_email` must stay behaviorally identical for both transports)

## 6. Deployment tasks

- [ ] Add the new Graph-related settings (tenant ID, client ID, client secret, mailbox UPN, `clientState` secret) to `unified-backend/.env` locally and to the Render environment for `unified-backend` — per this repo's own deployment conventions (see root `CLAUDE.md`'s "Deployment" section), remembering that `Settings` is `@lru_cache`d and a running process won't pick up `.env` changes without a restart
- [ ] Store the client secret securely in the deployment platform's secret store (Render environment variable, marked secret) — never commit it
- [ ] Confirm the deployed `unified-backend`'s public HTTPS URL is stable before registering it as the Graph subscription notification URL (a URL change would require re-creating the subscription)
- [ ] Register/create the Graph webhook subscription against the **production** notification URL once deployed (subscriptions are environment-specific — a subscription pointed at a local ngrok tunnel won't help production)
- [ ] Set up the **subscription renewal** job in production (APScheduler, following the same in-process scheduler pattern this repo already uses for `SLASweepService` per `CLAUDE.md`'s "Deployment" section — avoid introducing a second, competing external scheduler)
- [ ] Monitor Render logs after deploy for successful subscription creation/renewal and for any Graph auth failures, the same way SLA sweep completion is currently confirmed via log lines
- [ ] Decide and document the **cutover plan** for N8N: run Graph and N8N in parallel for a validation period, or cut over directly, and communicate whichever is chosen to whoever manages the N8N workflow
- [ ] Update this repo's `CLAUDE.md` (root) and `unified-frontend/CLAUDE.md` once real Graph integration lands — the current docs don't mention Graph at all, and per this repo's own documentation discipline (see the "drift" callouts throughout `CLAUDE.md`), stale docs here would repeat the same problem already fixed elsewhere in the project
- [ ] Rotate/verify the client secret's expiration date is tracked somewhere (Azure client secrets expire, e.g. every 6/12/24 months) so the integration doesn't silently break on secret expiry — no different in spirit from this repo's existing `JWT_SECRET_KEY` rotation caution, but for a credential Azure itself expires on a schedule
