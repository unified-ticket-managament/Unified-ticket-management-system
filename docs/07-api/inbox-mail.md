# Inbox / Mail API

Source: `app/ticketing/api/inbox.py` (prefix `/inbox`). Service: `InboxService`/`InteractionService`/`OpenEmailService`. This is the pre-ticket mailbox view — see [03-business-workflows/communication](../03-business-workflows/communication/) for how an inbound email arrives here before optionally becoming a ticket.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/inbox` | List inbox items (`view`/`scope`/`folder`, paginated) | `get_current_agent` |
| GET | `/inbox/folder-counts` | Per-custom-folder item counts | `get_current_agent` |
| GET | `/inbox/view-counts` | Pending/Replied/Ticketed/Archived/All badge counts | `get_current_agent` |
| GET | `/inbox/sent` | Every brand-new compose email the caller sent | `get_current_agent` |
| GET | `/inbox/replied` | Every reply the caller sent | `get_current_agent` |
| GET | `/inbox/drafts` | Every draft the caller saved | `get_current_agent` |
| POST | `/inbox/compose` | Author a brand-new outbound email (multipart, attachments) | `get_current_agent` |
| POST | `/inbox/{id}/forward` | Forward a client email to an internal org user (any active user, any role) | `get_current_agent` |
| POST | `/inbox/{id}/claim` | Claim a pending, unticketed inbox item | `get_current_agent` |
| POST | `/inbox/{id}/archive` | Mark item Informational/Archive | `get_current_agent` |
| PATCH | `/inbox/{id}/tags` | Replace tag list | `get_current_agent` |
| PATCH | `/inbox/{id}/folder` | File/unfile into a custom folder | `get_current_agent` |
| PUT | `/inbox/{id}/draft` | Upsert an auto-saving draft reply | `get_current_agent` |
| POST | `/inbox/{id}/draft/attachments` | Attach files to an in-progress draft | `get_current_agent` |
| POST | `/inbox/{id}/draft/send` | Send the current draft as a real reply | `get_current_agent` |
| DELETE | `/inbox/{id}/draft` | Discard a draft without sending | `get_current_agent` |
| GET | `/inbox/{id}` | Open full email/thread details | `get_current_agent` |
| POST | `/inbox/{id}/reply` | Reply on a pre-ticket conversation | `get_current_agent` |

## Key business rules

**Forward-to-internal-user visibility gap (fixed 2026-08-15)**: opening a forwarded item used to unconditionally 403 for the recipient, even holding `communication:view_all`, because `OpenEmailService.get_email_details`'s pending-item gate (`ensure_agent_can_view_pending_interaction`) had no permission-claim check at all. Fixed by adding an opt-in `view_only=True` flag that additionally admits anyone holding `communication:view_all` — deliberately only widens *viewing*, never claim/archive/reply/act actions on someone else's pending mail. See [14-troubleshooting/email](../14-troubleshooting/email/).

**Drafts are keyed on `interaction_id`, not `ticket_id`** — this is why attaching files to a pre-ticket draft works at all (an `Attachment` row references the interaction directly).

**First Response SLA visibility**: `GET /inbox` and `GET /inbox/{id}` both return an optional `first_response_sla` object (real clock state — `PENDING`/`COMPLETED` with `completion_reason`), not a client-computed estimate. A message whose clock was completed by the OTP-recognition path (see [SLA & Escalation](../03-business-workflows/sla/) workflow) now correctly shows as completed here rather than a stale ticking countdown.

**OTP recognition (rewritten 2026-08-21)**: whether an inbound email's First Response SLA clock auto-completes is now decided by a pure heuristic text classifier (`app/ticketing/services/otp_classifier.py`), evaluated *before* the Mail/OTP Rules engine runs at all — not by an `OTP_RULE` category rule match. The rule engine still evaluates independently afterward for folder filing and `forward_to` employee notifications, but its result no longer affects SLA completion in any way. See [03-business-workflows/communication/email-processing.md](../03-business-workflows/communication/email-processing.md) and [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md).

## Side effects

- `POST /inbox/compose`, `/reply`, `/draft/send` each create an `Interaction` row and, where applicable, dispatch a real outbound email via the Graph/SMTP transport.
- `POST /inbox/{id}/forward` creates a `MAIL_FORWARDED` notification to the target internal user — delivered via the normal `NotificationService.notify()` path, not the scoped inbox query, which is precisely why the recipient needed the `view_only` gate above to actually open it.
- `claim`/`archive`/`tags`/`folder` all write to the underlying `Interaction`/`inbox`-view state; none of these create a ticket by themselves (that's `POST /tickets/from-interaction`, see [tickets.md](tickets.md)).
