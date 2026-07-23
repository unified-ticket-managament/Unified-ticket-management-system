# Outgoing Email Flow

## Finding: `GraphEmailSender` does not exist

Same result as the last two reviews (`graph_client.py`, Graph authentication): a repo-wide filename and content search for `GraphEmailSender` (case-insensitive) returned **zero matches**. There is no Graph-backed sender of any kind in this codebase.

What follows instead is the **real, working outgoing-email flow** as it actually exists in `unified-backend/app/ticketing/` today — two parallel implementations, neither of which talks to Graph (see `EMAIL_INTEGRATION_ANALYSIS.md` for why there are two). This document traces both, covering every stage you asked about: draft creation, send, attachments, reply support, threading, and error handling.

---

## The two outgoing paths

| | Ticket-linked reply / Compose (in production use) | Standalone provider seam (mocked, unwired) |
|---|---|---|
| Entry point | `InteractionService.add_reply` / `add_interaction_reply` / `compose_email` | `POST /api/mail/outgoing` → `OutgoingMailService.send_email` |
| Envelope builder | `build_reply_envelope` / `build_compose_envelope` (`services/email_envelope.py`) | `build_compose_envelope` (when `client_id` given) or a raw `OutboundEnvelope` |
| Actual transport | `OutboundDispatcher.dispatch()` — no-op logger | `MailProviderClient.send_email()` — `MockMailProviderClient`, no-op |
| Has drafts? | Yes | No |
| Has attachments? | Yes | No (no attachment field on `OutgoingEmailRequest` at all) |

Both produce the same `OutboundEnvelope` shape (`schemas/payloads/outbound_envelope.py`) and neither actually delivers mail anywhere — this document focuses on the left column, since it's the one with draft/attachment/reply/threading behavior to explain; the right column is covered in full already in `EMAIL_API_DOCUMENTATION.md` §1.

---

## 1. Draft creation

Backing the Mail v2 auto-saving draft feature (`interaction_service.py`, lines ~2035–2295). A draft is stored as a real `Interaction` row, not a client-side-only concept.

- **`_get_or_create_draft`** (line 2035): fetches the current agent's existing draft on a thread (`is_draft=True`, scoped per `(parent_interaction_id, performed_by)`), or creates an empty one. One active draft per thread **per agent** — enforced by a partial unique index, `ix_interactions_one_draft_per_thread_per_agent`, on `(parent_interaction_id, performed_by) WHERE is_draft AND is_visible`.
- **Race handling**: the frontend calls `save_draft` continuously (debounced) as the user types, so two near-simultaneous requests can both miss the existing-draft check and both try to insert. The losing insert fails with `IntegrityError` (caught inside a `begin_nested()` savepoint), which is treated as "someone else's insert won" — the loser just re-fetches and returns that draft instead of erroring.
- **`save_draft`** (line 2105): upserts current-user's draft with whatever `message`/`cc`/`bcc` the frontend sent — overwritten, not versioned, on every save. Stored payload includes `"dispatch_status": "DRAFT"`.
- **`upload_draft_attachment`** (line 2151): attaches files to the draft — creates an empty draft row first if the agent attaches a file before typing anything (see §3).
- Drafts are **pre-ticket only** — `_resolve_pending_thread_root` 400s if the thread has already become a ticket, mirroring the same restriction on `add_interaction_reply`.
- **`discard_draft`** (line 2259): deletes the draft row and any attachments already uploaded to it (both the DB row and the underlying storage object) — otherwise a discarded draft's files would linger in storage with nothing left to clean them up.

## 2. Send operation

### Sending a saved draft
**`send_draft`** (line 2199) does not have its own send logic — it reads the draft's saved `message`/`cc`/`bcc`, then calls `add_interaction_reply` with them (the exact same code path a normal, non-draft reply takes — "there is deliberately no separate 'draft becomes a reply' code path to keep that logic in exactly one place"). `to_email` (a "To" dropdown override) is accepted as a send-time-only parameter, not part of the auto-saved draft payload, since it's only meaningful at the moment of sending. After the reply interaction is created, any files already uploaded against the draft are **reassigned** onto the new reply's `interaction_id` (`attachment_repository.reassign_interaction`), then the now-obsolete draft row is deleted.

### Sending a reply directly (no draft involved)
`add_reply` (ticket-linked, line 602) and `add_interaction_reply` (pre-ticket thread, line 724) both follow the same shape:
1. Resolve the latest inbound email on the thread/ticket (`get_latest_inbound_email_for_ticket` or the thread root itself) — this supplies the recipient address and `In-Reply-To` value.
2. Build an `OutboundEnvelope` via `build_reply_envelope` (§4).
3. Persist an `OUTBOUND` `Interaction` with `payload.envelope` and `payload.dispatch_status = "QUEUED"`.
4. Write a `REPLY_ADDED` audit event (metadata only — the reply body itself is never audit-logged).
5. Call `self.outbound_dispatcher.dispatch(interaction.interaction_id, envelope)` — today, `OutboundDispatcher.dispatch()` (`services/outbound_dispatcher.py`) is a **pure no-op**: it logs `"queued outbound email: ..."` and returns. Nothing leaves the platform. The interaction's `dispatch_status` stays `"QUEUED"` forever — nothing ever flips it to `SENT`/`FAILED`, since no real transport exists to report either outcome.

### Composing a brand-new email (no prior thread)
`compose_email` (line 859) is the one send path with no existing interaction to reply onto — it creates a new thread **root** (`interaction_type="EMAIL"`, `parent_interaction_id=NULL`, `ticket_id=NULL`) via `build_compose_envelope`, stored with the identical `envelope`/`dispatch_status="QUEUED"` shape a reply gets, "so it renders through the exact same Mail UI/thread-open code path afterward — nothing downstream needs to know a message started life as a Compose rather than a Reply."

## 3. Attachments

- Storage is keyed on `interaction_id` alone, **never** `ticket_id` — the same convention used for inbound email intake and Compose (`AttachmentService.validate_and_store_files`), which is why draft attachments needed no new storage capability, only a route/service seam exposing the existing one for a draft.
- `upload_draft_attachment` calls `_get_or_create_draft` first (so attaching a file before typing any text still has somewhere to attach to), then `AttachmentService.validate_and_store_files(files, draft.interaction_id)`.
- On `send_draft`, attachments follow the draft via `attachment_repository.reassign_interaction(draft_interaction_id, reply.interaction_id)` — they're re-pointed at the new reply interaction, not re-uploaded, since the draft row is about to be deleted.
- On `discard_draft`, each attachment is explicitly removed from both storage (`storage_service.delete`) and the DB (`attachment_repository.delete`) before the draft row itself is deleted.
- **Gap, consistent with `EMAIL_INTEGRATION_CHECKLIST.md`**: the standalone `/api/mail/outgoing` seam has no attachment support at all — `OutgoingEmailRequest` has no attachment field, and `OutgoingMailService`/`MailProviderClient` never touch `AttachmentService`. Attachments only work through the reply/Compose/draft path described above.

## 4. Reply support

`build_reply_envelope` (`services/email_envelope.py`, lines 39–93) is the single place reply semantics are enforced:

- **From** is always the client's shared inbox address (`client.inbox_email`) — **never** an agent's personal address, "that's what keeps the client's next answer routable back through the platform." `agent_name` is display-only.
- **To** defaults to the original sender (`inbound_payload.from_email`), overridable via `to_email_override` if the agent picked a different contact from a "To" dropdown — but an override still requires *some* resolvable recipient; it can't be used to bypass the no-recipient case below.
- **Subject** gets a `Re: ` prefix via `_reply_subject`, guarded against accumulating `Re: Re: Re: ...` if the original subject already starts with `Re:` (case-insensitive).
- **Cc** is merged (`_merge_cc`): the client's Account Manager is auto-added (so they see every reply in their real mailbox without checking the platform) alongside whatever the agent typed into the reply form's own Cc field — agent-entered addresses first, de-duplicated, order-preserving.
- **No-recipient case**: if there's no sender to reply to at all (e.g. a reply on a ticket whose originating email is unknown), `build_reply_envelope` returns `None` — callers treat this as "nothing to dispatch," not an error: the interaction is still created and persisted, but with `payload.dispatch_status = "NO_RECIPIENT"` instead of `"QUEUED"`, and `outbound_dispatcher.dispatch()` is simply never called.

`build_compose_envelope` is the same shape minus reply-specific derivation (no `inbound_payload` to pull To/Subject/References from — the agent supplies a real `to_email`/`subject` directly via the form), so it has no "nothing to dispatch" case.

## 5. Conversation threading

Threading is enforced at two layers — envelope headers (for the client's own mail client) and internal parent/child linkage (for this platform's own thread view):

- **Message-ID generation**: `_new_message_id` (`email_envelope.py`) fabricates a new RFC-5322-style Message-ID (`<{uuid4().hex}@{domain}>`, domain derived from the From address) for every outbound envelope — reply or compose alike. This is stored on the envelope and on the `Interaction.message_id` column so a **future inbound reply's `In-Reply-To`** can be matched back to it (see `EmailService.receive_email`'s own threading logic, covered in `EMAIL_INTEGRATION_ANALYSIS.md`/`EMAIL_API_DOCUMENTATION.md`).
- **`In-Reply-To`**: set to the inbound message's own `message_id` on a reply envelope; `None` on a Compose (nothing to reply to yet).
- **`References`**: the inbound message's own `references` list, with its `message_id` appended — the standard RFC 5322 "growing chain" convention, so a client's mail thread stays intact even many replies deep.
- **Internal parent linkage**: separate from the envelope headers, `add_reply`/`add_interaction_reply` resolve `thread_root_id` via `InteractionRepository.find_thread_root` — a **recursive** walk-up (not a single hop), so replying on a reply (or a deeply nested descendant) still threads under the true original conversation root rather than forking. The new interaction's `parent_interaction_id` is set to that resolved root.
- **`conversation_id`**: accepted on the inbound side (`EmailRequest.conversation_id`, described in its own docstring as "Microsoft Graph's own conversation identifier — unavailable until Task 1 ships; accepted now (optional) so this schema doesn't need to change again once it does") but **outbound envelopes never set one** — `OutboundEnvelope` has no `conversation_id` field at all. Threading on the outbound side today relies entirely on `message_id`/`in_reply_to`/`references`, not a Graph-style conversation identifier.

## 6. Error handling

There is very little to describe here, because almost nothing in this flow can currently fail at the transport layer — by design, since no real transport exists yet:

- **`OutboundDispatcher.dispatch()`** cannot fail — it only logs and returns `None`. Its own docstring states the intended future behavior directly: "Task 1 replaces `dispatch()` with real SMTP/API delivery and is responsible for updating that status to `SENT` or `FAILED` once it does." Until then, every dispatched interaction's `dispatch_status` is permanently `"QUEUED"`, with no code path that ever transitions it further.
- **No-recipient handling** is the one real "failure" the reply flow already handles gracefully: rather than raising an error when no valid recipient can be resolved, `build_reply_envelope` returns `None`, and the caller stores the interaction anyway with `dispatch_status = "NO_RECIPIENT"` — a deliberate, visible-in-the-UI state rather than a thrown exception or a silently dropped reply.
- **Draft-creation race** (`IntegrityError` from the partial unique index) is caught and resolved by re-fetching the winning draft, as described in §1 — not surfaced to the caller as an error at all.
- **Attachment storage failures**: `upload_draft_attachment` returns `503` if `attachment_repository`/`storage_service` aren't configured, and `400` if no files were provided — ordinary input/config validation, not transport error handling.
- **The standalone `/api/mail/outgoing` route** (`OutgoingMailService`/`MockMailProviderClient`) has exactly one error path today: an unknown `client_id` raises `ValueError("Client not found.")`, mapped to `404` by the route handler. `MockMailProviderClient.send_email` itself cannot fail — it always returns `status="SENT"`.

**What's missing, consistent with `EMAIL_INTEGRATION_CHECKLIST.md`**: no retry/backoff logic, no distinction between a transient failure (worth retrying) and a permanent one (bad address, rejected by the provider), no dead-letter/failed-send visibility for an agent to notice and re-send, and no real `SENT`/`FAILED` status transition anywhere — all of it is deferred to whichever future transport (Graph or otherwise) replaces both `OutboundDispatcher.dispatch()` and `MockMailProviderClient.send_email()`.
