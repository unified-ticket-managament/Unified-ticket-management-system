# Communication Management Module

## Purpose
Capture, thread, and let agents act on every client communication — before, during, and independent of whether a ticket exists yet.

## Responsibilities
- Inbound email intake (Graph webhook/poll, or generic relay).
- Client identification and thread detection.
- Pending-item triage: claim, archive, tag, file into folders.
- Compose/reply/forward, with real attachment support and auto-saving drafts.
- Internal Notes with real, hierarchy-free recipient delivery.
- Mail/OTP automation rules.

## Main Components
- `app/ticketing/api/{inbox,interaction,email,mail_integration,mail_folder,rule}.py`
- `app/ticketing/services/{email_service,inbox_service,inbox_ticket_service,interaction_service,open_email_service,mail_folder_service,rule_engine_service,rule_service,outbound_dispatcher,undo_send}.py`
- `app/ticketing/models/{interaction,mail_folder,message_read_receipt,rule}.py`

## Inputs
Inbound email (Graph/relay), agent compose/reply/forward/note actions.

## Outputs
Threaded `Interaction` rows; the Mail/Inbox UI's data; outbound email dispatch.

## Business Rules
- A reply always resolves to the thread root — SLA clocks and ticket association never key off an intermediate message.
- Internal Note recipients: `recipient_user_ids` snapshot into the Interaction's `payload`; when given, `notify()` targets exactly that set; empty falls back to the legacy stakeholder set (assigned agent + Team Lead + Account Manager).
- The internal-note recipient picker (`GET /tickets/internal-notes/recipients`) is **deliberately unscoped by hierarchy** — any active user, any role — a real requirement, not an oversight, since RBAC's own `GET /users` is hierarchy-scoped and would have broken this for Staff/Account Manager/Team Lead senders.
- Drafts are keyed on `interaction_id`, not `ticket_id` — this is why attaching files to a pre-ticket draft works (an `Attachment` references the interaction directly).
- Forwarding to an internal user creates a `Notification`, not a scoped-inbox-query entry — this is why opening a forwarded item needed its own `communication:view_all`-aware visibility fix (see [14-troubleshooting/email](../../14-troubleshooting/email/)).
- **OTP recognition (superseded 2026-08-21)**: First Response SLA completion for a recognized one-time-passcode email is now driven by a pure heuristic text classifier (`otp_classifier.py`), not Mail/OTP Rule keyword matching — the rule engine still runs for folder filing/forwarding, but the two are now fully independent. See [ai-nlp.md](ai-nlp.md) and [03-business-workflows/communication/email-processing.md](../03-business-workflows/communication/email-processing.md).

## Dependencies
`ClientService` (identification), `SLAService` (First Response clock), `RuleEngineService`, `NotificationService`, storage backend (attachments).

## Database Entities
`interactions`, `mail_folders`, `message_read_receipts`, `rules`, `attachments`.

## APIs
[07-api/inbox-mail.md](../07-api/inbox-mail.md), [07-api/mail-integration.md](../07-api/mail-integration.md), [07-api/clients-categories-rules.md](../07-api/clients-categories-rules.md) (rules).

## Important Classes/Services
`EmailService`, `InboxService`, `InteractionService`, `RuleEngineService`.

## External Integrations
Microsoft Graph (mailbox), SMTP (outbound), object storage (attachments).

## Known Limitations
- The standalone `ticketing-service/frontend` never received the "Mail v2" two-panel redesign — as of 2026-08-21 it has no files left at all (not even its former stale `dist/` bundle, which was deleted), so this is fully moot, but means anyone expecting parity between "the two frontends" is working from a false premise.
- CC/BCC on replies have real backend delivery but no auto-population; Internal Note's own informational "To" dropdown (distinct from the newer real-recipient feature) is not sent to the backend in some UI surfaces.
- A rule's `client` condition is an exact-match filter, not an implicit "this client or none" — a real incident (an OTP rule scoped to the wrong client) came from this.

## Related workflows
[03-business-workflows/communication](../../03-business-workflows/communication/) (all three documents), [03-business-workflows/ticket/ticket-processing.md](../../03-business-workflows/ticket/ticket-processing.md) (reply/note actions).
