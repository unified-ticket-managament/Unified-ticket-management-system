# Mail Integration API (inbound/outbound transport)

Source: `app/ticketing/api/mail_integration.py` (prefix `/api/mail`), `app/ticketing/api/email.py` (prefix `/emails`). These are the transport-layer endpoints behind the Inbox/Mail domain documented in [inbox-mail.md](inbox-mail.md) — see [03-business-workflows/communication](../03-business-workflows/communication/) for the end-to-end inbound-email flow.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/mail/outgoing` | Dispatch a frontend-authored email through the configured mail provider | `get_current_agent` |
| POST | `/api/mail/incoming` | Microsoft Graph webhook receiver — validation handshake + change-notification batch, processed via a background task, returns 202 | **None** — unauthenticated; integrity enforced via Graph's `clientState` match, not a bearer token |
| GET | `/api/mail/incoming` | Validation-handshake alias for providers that probe with GET | **None** — unauthenticated |
| POST | `/emails/incoming` | Real inbound-email transport (N8N/Graph relay, form-encoded) | **None** — unauthenticated service-to-service |
| POST | `/emails/dummy` | Internal "Create Dummy Mail" simulator, for testing without real inbound email | `get_current_agent` + role check: caller's role must be in `DUMMY_MAIL_ROLE_NAMES` (Site Lead only, confirmed) |

## Security note on the two unauthenticated inbound routes

`POST /api/mail/incoming` and `POST /emails/incoming` are deliberately reachable with no JWT — they're invoked by Microsoft Graph and/or an N8N relay, neither of which can present a bearer token in the same way a logged-in browser session can. `/api/mail/incoming`'s integrity check is Graph's own `clientState` value (a shared secret embedded in the subscription, compared on receipt) rather than a header token. Treat both endpoints as a real attack surface if network-level restriction (IP allowlisting, a reverse-proxy secret, etc.) isn't already layered in front of them — **not confirmed** whether any such network-level protection exists; verify with whoever manages the Render/infra configuration before assuming these are safely exposed as-is. See [08-security](../08-security/README.md).

## Business logic (`EmailService.receive_email`, `otp_classifier`, `RuleEngineService`)

Every inbound email goes through client-identification/threading, then (as of 2026-08-21) a pure heuristic OTP classifier (`otp_classifier.classify_otp_email`, no DB/I/O/external dependency) decides whether to complete the First Response SLA clock immediately (`SLAService.complete_first_response_clock`, `completion_reason="OTP_RECOGNIZED"`), inline in the same DB transaction as the clock's own creation — no external reader can ever observe a matching email's clock in a "started but not stopped" intermediate state. **Only after this** does `RuleEngineService.evaluate_and_execute_for_email` run, independently, for Mail/OTP Rule-driven folder filing and forwarding — its result no longer has any bearing on SLA completion (a change from the previous keyword-rule-driven design). See [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md).

Attachment extraction (real Graph inbound attachments) goes through `build_upload_files_from_graph_attachments` (`mail_mapping_service.py`) — see [16-known-limitations/integration-limitations.md](../16-known-limitations/integration-limitations.md) for three real, stacked bugs found and fixed in this exact pipeline (odata_type gating, MIME-type validation, and a Graph `$select` OData incompatibility).
