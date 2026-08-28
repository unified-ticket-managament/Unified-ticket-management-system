// ==========================================================
// Shared enum-like string literal types
// (mirrors backend app/enums)
// ==========================================================

export type InteractionStatus = "PENDING" | "ASSIGNED" | "IGNORED";

export type InteractionDirection = "INBOUND" | "OUTBOUND" | "INTERNAL";

export type TicketStatus =
  | "OPEN"
  | "IN_PROGRESS"
  | "PENDING"
  | "WAITING_FOR_CLIENT"
  | "RESOLVED"
  | "CLOSED";

// CRITICAL is deliberately not manually selectable anywhere — it's set
// automatically, once, when a ticket's escalation workflow creates its
// first escalation, and stays permanently thereafter. Every manual
// "Change Priority"/"Create Ticket" priority picker must keep using
// its own narrower LOW/MEDIUM/HIGH-only list rather than this full
// union; only display/filter surfaces should show CRITICAL.
export type TicketPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

// ==========================================================
// Categories — work-specialization categories (Eligibility, AR,
// Claims, ...) owned by the RBAC service; a ticket's `ticket_type`
// is one of these category names, fetched live via GET /categories
// rather than a fixed frontend enum.
// ==========================================================

export interface CategoryResponse {
  category_id: string;
  category_name: string;
  inbox_email: string | null;
}

// ==========================================================
// Email
// ==========================================================

export interface EmailRequest {
  to_email: string;
  from_email: string;
  from_name?: string;
  subject: string;
  body: string;
  html_body?: string;
  message_id: string;
  received_at?: string;
  in_reply_to?: string;
  references?: string;
  conversation_id?: string;
}

export interface EmailResponse {
  message: string;
  interaction_id: string;
  client_id: string;
  client_name: string;
  ticket_id: string | null;
  threaded_under: string | null;
  status: string;
  attachments?: AttachmentMeta[];
}

// ==========================================================
// Clients — a client company, identified by the dedicated
// shared inbox address it was given at onboarding.
// ==========================================================

export interface ClientCreateRequest {
  name: string;
  inbox_email: string;
  account_manager_id: string;
}

export interface ClientResponse {
  client_id: string;
  name: string;
  // The client's official distribution/intake address — null when it
  // has none configured (never inferred from a contact/employee
  // address; see the backend Client model's own docstring).
  inbox_email: string | null;
  account_manager_id: string;
  is_active: boolean;
  created_at: string;
  account_manager_name: string | null;
  account_manager_active: boolean;
}

// One personal address this client company has contacted our shared
// inbox from — backs the reply composers' "To" dropdown.
export interface ClientContact {
  email: string;
  name: string | null;
}

// GET /clients/{client_id}/details — gated by client:view. Used only
// by the Roles page's Client-tab expand action.
export interface ClientDetailsResponse extends ClientResponse {
  contacts: ClientContact[];
}

// ==========================================================
// Attachments
// ==========================================================

export interface AttachmentMeta {
  id: string;
  filename: string;
  mime_type: string | null;
  size: number | null;
  download_url: string;
  preview_url?: string | null;
  // True for a OneDrive/SharePoint cloud-link reference with no real
  // stored bytes — download_url is the original external URL (opens
  // in a new tab), not a link to our own storage.
  is_external_link?: boolean;
  // Set only for a pasted-into-the-body inline image (Outlook-style
  // clipboard paste) — the value referenced as `cid:{content_id}` in
  // the composer's HTML body. Absent/undefined for an ordinary
  // attachment.
  content_id?: string | null;
  is_inline?: boolean;
}

// Response for the dedicated single-file inline-image upload
// endpoints (POST .../attachments/inline-image) — a paste event
// uploads exactly one image at a time and needs its content_id back
// immediately to build `cid:{content_id}` client-side, with no
// second round trip.
export interface InlineImageUploadResponse {
  id: string;
  content_id: string;
  filename: string;
  mime_type: string | null;
  size: number | null;
  preview_url?: string | null;
  // The interaction this attachment is currently stored against — a
  // fresh, dedicated interaction for the ticket-scoped endpoint (see
  // AttachmentService.upload_inline_image), or the draft's own
  // interaction for the pre-ticket endpoint (already handled by
  // send_draft's existing reassignment — no action needed for that
  // case). Ticket-scoped callers must collect this and submit it back
  // as one of ReplyRequest/InternalNoteRequest's
  // inline_image_interaction_ids at Send time.
  interaction_id: string;
}

// One row of a ticket's complete attachment history (GET
// /tickets/{id}/attachments) — every attachment across every
// interaction type on the ticket, not just whichever message is
// currently open. See TicketAttachmentsTab.tsx.
export interface TicketAttachmentItem extends AttachmentMeta {
  interaction_id: string;
  interaction_type: string;
  performed_by: string | null;
  performed_by_name: string | null;
  created_at: string;
}

// ==========================================================
// Agents
// ==========================================================

export interface AgentSummary {
  user_id: string;
  name: string;
  email: string;
  employee_number?: string | null;
}

// Who the current user may assign a brand-new ticket to on the
// Create Ticket dialog — see GET /agents/assignable, scoped per the
// caller's own role/hierarchy (AssignmentService on the backend).
export interface AssignableUserSummary {
  user_id: string;
  name: string;
  // Official, human-readable Employee ID (e.g. "266") — display only,
  // the picker's own selected value is always user_id.
  employee_number?: string | null;
  // Display-only Leave indicator — see shared_models.models.User.
  // is_on_leave's own docstring. Never narrows/reorders this picker;
  // formatAssigneeLabel appends "(Leave)" to the name when true.
  is_on_leave?: boolean;
}

export interface AssignableGroup {
  role: string;
  users: AssignableUserSummary[];
}

export interface AssignableAgentsResponse {
  // null only for EscalationService.get_acknowledge_candidates' one
  // exception: a Reporting-Manager-tagged escalation owner may not
  // assign the ticket to themselves — every other caller of this
  // shape (the Create Ticket / Reopen pickers) still always returns a
  // real value.
  me: AssignableUserSummary | null;
  groups: AssignableGroup[];
}

// ==========================================================
// Auth — RBAC-issued identity (login/refresh/me all live on
// the RBAC service, this app only consumes them)
// ==========================================================

export interface CurrentUser {
  user_id: string;
  name: string;
  email: string;
  role: string;
  role_id: string;
  is_active: boolean;
  permissions: string[];
  scoped_permissions?: Record<string, string[]>;
  employee_number?: string | null;
}

// ==========================================================
// Account Manager Inbox
// ==========================================================

export type InboxView = "pending" | "replied" | "ticketed" | "archived" | "all";
export type InboxScope = "mine" | "all";

export interface InboxItem {
  interaction_id: string;
  // Only set for Sent/Draft-derived rows, where clicking must open the
  // thread ROOT rather than this row's own id (see sentItemToInboxItem/
  // draftItemToInboxItem in useMailInbox.ts). Absent for every regular
  // inbox row, where interaction_id already IS the thread root by
  // construction (list_inbox only ever returns roots).
  open_interaction_id?: string;
  client_id: string | null;
  client_name: string;
  // Set instead of client_id/client_name for a CATEGORY-mailbox item
  // (never both) — distinguishes a "Category Inbox" row from a
  // "Client Inbox" one.
  category_id?: string | null;
  category_name?: string | null;
  from_email: string | null;
  to_email: string | null;
  subject: string;
  message_id: string | null;
  received_at: string;
  status: InteractionStatus;
  direction: InteractionDirection;
  ticket_id: string | null;
  ticket_priority: TicketPriority | null;
  ticket_category: string | null;
  has_attachments: boolean;
  claimed_by: string | null;
  claimed_by_name: string | null;
  tags: string[];
  folder_id: string | null;
  reply_count: number;
  latest_message: string | null;
  latest_sender: string | null;
  latest_at: string | null;
  // Real, DB-backed First Response SLA state for this row's thread
  // root — null once ticketed or if no clock exists. See
  // FirstResponseSLAState's own definition below.
  first_response_sla?: FirstResponseSLAState | null;
  // Persisted read state (message_read_receipts) for the current
  // user — real backend truth, unlike the client-only openedIds Set
  // this superseded. Optional so any stale-shaped cached response
  // still degrades to the old openedIds-based rendering.
  is_read?: boolean;
  // Only set (true) on a Drafts-tab row derived from a Compose draft
  // (draftItemToInboxItem, when the underlying DraftItem.root_
  // interaction_id was null — a Reply draft always has a real root).
  // Opening such a row must reopen the Compose form pre-filled, never
  // the generic "open this thread" flow (there is no thread to open).
  is_compose_draft?: boolean;
}

export interface InboxResponse {
  total: number;
  items: InboxItem[];
}

// ==========================================================
// Notifications — reused by both the topbar bell (in-app alerts) and
// the Mail page's "System" folder (same GET /notifications data,
// rendered in a mail-style read view — see useMailInbox.ts).
// ==========================================================

export interface NotificationItem {
  notification_id: string;
  notification_type: string;
  title: string;
  message: string;
  link: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  total: number;
  unread_count: number;
  items: NotificationItem[];
}

export interface InteractionClaimResponse {
  interaction_id: string;
  claimed_by: string | null;
  claimed_by_name: string | null;
  claimed_at: string | null;
  message: string;
}

export interface InteractionArchiveResponse {
  interaction_id: string;
  status: InteractionStatus;
  message: string;
}

export interface OpenEmailResponse {
  interaction_id: string;
  ticket_id: string | null;
  client_id: string | null;
  client_name: string;
  // See InboxItem's matching fields — set instead of client_id/
  // client_name for a CATEGORY-mailbox thread, never both.
  category_id?: string | null;
  category_name?: string | null;
  to_email: string | null;
  // Every real "To" recipient when a Compose-authored send had more
  // than one — empty for an inbound email or a single-recipient send,
  // in which case a display surface should fall back to to_email.
  to_emails: string[];
  from_email: string | null;
  from_name: string | null;
  cc: string[];
  bcc: string[];
  to_recipients: string[];
  subject: string;
  body: string;
  // The sanitized-on-ingest HTML counterpart to `body`, set for any
  // HTML-content-type inbound email (not just an agent-authored
  // outbound send) — see the backend's OpenEmailResponse.body_html.
  // null/undefined falls back to the existing plain-text rendering.
  body_html?: string | null;
  message_id: string | null;
  received_at: string;
  status: InteractionStatus;
  claimed_by: string | null;
  claimed_by_name: string | null;
  account_manager_name: string | null;
  ticket_priority: string | null;
  ticket_category: string | null;
  ticket_status: string | null;
  tags: string[];
  folder_id: string | null;
  // Persisted read state (message_read_receipts) — always true here,
  // since opening this endpoint is itself what records the receipt.
  is_read: boolean;
  draft_message: string | null;
  draft_cc: string[];
  draft_bcc: string[];
  draft_attachments: AttachmentMeta[];
  attachments?: AttachmentMeta[];
  replies: InteractionResponse[];
  recommended_ticket_id: string | null;
  recommended_ticket_reason: string | null;
  // Real, DB-backed First Response SLA state for this thread's root
  // interaction — null once ticketed or if no clock exists.
  first_response_sla?: FirstResponseSLAState | null;
}

export interface InteractionTagsResponse {
  interaction_id: string;
  tags: string[];
  message: string;
}

export interface InteractionFolderResponse {
  interaction_id: string;
  folder_id: string | null;
  message: string;
}

export interface MailFolder {
  folder_id: string;
  name: string;
  created_by: string | null;
  created_at: string;
}

export interface SentItem {
  interaction_id: string;
  root_interaction_id: string | null;
  ticket_id: string | null;
  client_id: string | null;
  client_name: string;
  subject: string;
  message: string;
  sent_at: string;
}

export interface SentResponse {
  total: number;
  items: SentItem[];
}

export interface DraftItem {
  interaction_id: string;
  root_interaction_id: string | null;
  client_id: string | null;
  client_name: string;
  subject: string;
  message: string;
  created_at: string;
}

export interface DraftListResponse {
  total: number;
  items: DraftItem[];
}

export interface DraftSaveResponse {
  interaction_id: string;
  root_interaction_id: string;
  message: string;
  body_html?: string | null;
  cc: string[];
  bcc: string[];
  attachments: AttachmentMeta[];
  created_at: string;
}

export interface DraftDeleteResponse {
  message: string;
}

// Compose's own server-backed draft — a brand-new EMAIL-type root
// with is_draft=true and no parent (see the backend's
// ComposeDraftResponse), a deliberate sibling to DraftSaveResponse
// above (a pre-ticket Reply draft, keyed off a resolved thread root)
// rather than a shared shape, since a Compose draft carries its own
// client/category/recipient fields that a Reply draft borrows from
// its root instead.
export interface ComposeDraftResponse {
  interaction_id: string;
  client_id?: string | null;
  category_id?: string | null;
  to_email?: string | null;
  to_emails: string[];
  cc: string[];
  bcc: string[];
  subject: string;
  message: string;
  body_html?: string | null;
  attachments: AttachmentMeta[];
  created_at: string;
}

export interface ComposeDraftSaveRequest {
  client_id?: string | null;
  category_id?: string | null;
  to_email?: string | null;
  to_emails?: string[];
  cc?: string[];
  bcc?: string[];
  subject?: string;
  message?: string;
  body_html?: string | null;
}

// Ticket-scoped drafts — Save Draft for Ticket Reply and Internal
// Note (also used by Mail's own ticketed ReplyComposer, which sends
// through the same ticket-reply endpoints). A deliberate sibling to
// the pre-ticket/Compose draft shapes above, not a shared one — a
// ticket draft has no thread root or standalone-message concept, the
// ticket itself is the scope, and Reply/Internal-Note genuinely need
// different fields.
export interface TicketReplyDraftSaveRequest {
  to_email?: string | null;
  to_emails?: string[];
  cc?: string[];
  bcc?: string[];
  message?: string;
  body_html?: string | null;
}

export interface TicketReplyDraftResponse {
  interaction_id: string;
  ticket_id: string;
  to_email: string | null;
  to_emails: string[];
  cc: string[];
  bcc: string[];
  message: string;
  body_html: string | null;
  created_at: string;
}

export interface TicketNoteDraftSaveRequest {
  subject?: string;
  note?: string;
  body_html?: string | null;
  recipient_user_ids?: string[];
}

export interface TicketNoteDraftResponse {
  interaction_id: string;
  ticket_id: string;
  subject: string;
  note: string;
  body_html: string | null;
  recipient_user_ids: string[];
  created_at: string;
}

export interface InteractionReplyRequest {
  message: string;
  cc?: string[];
  bcc?: string[];
  // Distribution Lists to loop in on Cc, resolved server-side to
  // their current active members and merged in — never into
  // to_email. See ReplyCreate.distribution_list_ids (backend) for the
  // same field on the ticketed-reply counterpart.
  distribution_list_ids?: string[];
  // Single-recipient override — still accepted by the backend for
  // back-compat callers. Mail's ReplyComposer.tsx sends to_emails
  // below instead.
  to_email?: string | null;
  // Multiple "To" recipients for this reply — the plural, additive
  // counterpart the Reply composer's chip-based To field now sends
  // instead of a single string. When both are given, the backend
  // prefers to_emails.
  to_emails?: string[];
  // Selects Graph's native replyAll action over reply when the
  // message being replied to has a known Graph message id — mirrors
  // the Mail page's own Reply/Reply All toggle. Falls back to a
  // plain sendMail-based send when the backend has no Graph id to
  // reply against.
  reply_all?: boolean;
  // Optional sanitized-on-the-backend HTML counterpart to `message`
  // (Outlook-style clipboard paste — pasted rich text/tables/inline
  // images). Omit to send exactly like before this field existed.
  body_html?: string | null;
  // Client-generated Send idempotency key — see ComposeEmailPayload.
  // idempotencyKey (api/inbox.ts) for the same contract.
  idempotency_key?: string | null;
}

export interface InteractionReplyResponse {
  interaction_id: string;
  parent_interaction_id: string;
  message: string;
  created_at: string;
}

// ==========================================================
// Ticket
// ==========================================================

export interface RelatedTicketSummary {
  ticket_id: string;
  title: string;
  current_status: TicketStatus;
}

export interface TicketResponse {
  ticket_id: string;
  // Permanent, human-readable reference — display as `TKT-${ticket_number}`.
  // ticket_id above remains the real identifier for every API call/route.
  ticket_number: number;
  client_id: string | null;
  client_company_id: string | null;
  agent_id: string | null;
  created_by: string | null;
  title: string;
  ticket_type: string;
  current_status: TicketStatus;
  current_priority: TicketPriority;
  custom_fields: Record<string, unknown>;
  version: number;
  closed_at: string | null;
  closed_by: string | null;
  created_at: string;
  updated_at: string;
  client_name: string | null;
  client_company_name: string | null;
  agent_name: string | null;
  created_by_name: string | null;
  closed_by_name: string | null;

  // "Assigned By" — the user who performed the assignment (initial
  // pre-assignment at creation, a claim, or a transfer) that produced
  // the CURRENT agent_id above. Distinct from agent_id (current
  // assignee), created_by (who opened the ticket), and any Reporting
  // Manager relationship. A real, persisted column on the backend's
  // Ticket model, stamped explicitly by every assignment code path —
  // not derived at read time. Null for a still-unclaimed ticket, or a
  // pre-existing ticket with no derivable assignment history.
  assigned_by?: string | null;
  assigned_by_name?: string | null;
  related_tickets: RelatedTicketSummary[];

  // Escalation display fields — LEFT JOIN-sourced on the backend
  // (TicketRepository.list_visible_page), never a second per-row
  // lookup. `is_escalated` is the one signal the ticket-list page
  // needs to render the Critical/escalation badge and float a row to
  // the top of My Tickets — it never means the ticket's own
  // `current_priority` was overwritten; that field is untouched by
  // escalation state (see the backend schema's own docstring).
  is_escalated?: boolean;
  escalation_level?: EscalationLevel | null;
  escalation_status?: EscalationStatus | null;
  escalation_ack_due_at?: string | null;

  // True only when *the current viewer* is a listed owner of this
  // ticket's active escalation — not just "this ticket is escalated
  // to someone." A ticket escalated from Staff to Team Lead is still
  // visible to an Account Manager on the unrestricted "All" tab (that
  // tab shows everything by design), but they aren't a real owner
  // yet, so Acknowledge/Assign must stay hidden for them even though
  // `is_escalated`/`escalation_status` are both set. Gate the
  // Acknowledge action on this field, not on is_escalated alone.
  is_escalation_owner?: boolean;

  // True while is_escalated and the escalation hasn't yet been
  // *accepted* (acknowledged AND assigned) — mirrors the backend's
  // ensure_ticket_not_frozen_by_escalation gate exactly. Unlike
  // is_escalation_owner, this is NOT per-viewer: it's true for every
  // viewer alike, since nobody (supervisors included) may edit a
  // ticket frozen this way. Gate every edit action (reply, internal
  // note, status/priority change, transfer, attachment upload,
  // close/reopen) on this being false, not on role or ownership.
  escalation_pending_acceptance?: boolean;

  // Resolution SLA clock's own risk tier — same LEFT JOIN-sourced,
  // display-only shape as the escalation fields above, but an
  // independent signal (see lib/slaMath.ts's SlaTier — kept as an
  // inline literal here rather than importing from lib/, matching
  // this file's existing types-only role). Only 3 values, unlike
  // SlaTier's 4 — Resolution SLA has no BREACHED tier at all; its
  // sole terminal tier is "escalated", now at 100% elapsed rather
  // than 150%. None when there's no active Resolution SLA clock or
  // no matching policy.
  resolution_sla_tier?: "healthy" | "at_risk" | "escalated" | null;
}

export interface RelateTicketRequest {
  related_ticket_id: string;
}

export interface RelateTicketResponse {
  ticket_id: string;
  related_ticket_id: string;
  message: string;
}

export interface UnrelateTicketResponse {
  message: string;
}


export interface TransferAgentRequest {
  new_agent_id: string;
  reason: string;
  category_name?: string;
}

export interface TicketUpdateRequest {
  agent_id?: string | null;
  title?: string;
  ticket_type?: string;
  current_status?: TicketStatus;
  current_priority?: TicketPriority;
  custom_fields?: Record<string, unknown>;
  closed_at?: string | null;
}

export interface TicketFromInteractionRequest {
  interaction_id: string;
  title: string;
  ticket_type: string;
  current_priority?: TicketPriority;
  // Who to assign the new ticket to — omitted/undefined keeps the
  // original behavior (ticket born unclaimed, in the shared pool).
  agent_id?: string | null;
}

export interface TicketFromInteractionResponse {
  message: string;
  ticket_id: string;
  interaction_id: string;
  status: string;
}

export interface AttachInteractionRequest {
  interaction_id: string;
  // Only applied when the target ticket is CLOSED (this attach also
  // reopens it) — see MessageDetailsView.tsx's Attach dialog. Omit
  // both to keep the existing assignee/priority on reopen.
  new_agent_id?: string;
  new_priority?: TicketPriority;
}

export interface AttachInteractionResponse {
  message: string;
  ticket_id: string;
  interaction_id: string;
  status: InteractionStatus;
  ticket_reopened?: boolean;
}

// ==========================================================
// Interaction / Timeline
// ==========================================================

export interface InteractionResponse {
  interaction_id: string;
  ticket_id: string | null;
  interaction_type: string;
  status: InteractionStatus;
  direction: InteractionDirection;
  performed_by: string | null;
  performed_by_name?: string | null;
  // Set only when this row was written during an active "Login as
  // User" impersonation session — the real, physically-authenticated
  // Super Admin, distinct from performed_by/performed_by_name above
  // (which stay whoever's identity actually performed the action).
  // Undefined/null for every ordinary row.
  impersonator_id?: string | null;
  impersonator_name?: string | null;
  subject?: string | null;
  payload: Record<string, unknown>;
  is_visible: boolean;
  removed_by: string | null;
  removed_at: string | null;
  message_id: string | null;
  client_id?: string | null;
  parent_interaction_id?: string | null;
  received_at?: string | null;
  created_at: string;
  attachments?: AttachmentMeta[];
  conversation_id?: string | null;
  in_reply_to_message_id?: string | null;
  references?: string[];
  // Typed mirror of payload["dispatch_status"]/["dispatch_error"] for
  // an outbound send (Compose/Reply/Reply-All/Forward/Draft) — see
  // the backend's own InteractionResponse. null/undefined for every
  // interaction that was never an outbound dispatch attempt.
  dispatch_status?: string | null;
  dispatch_error?: string | null;
}

// GET /interactions/{id}/thread
export interface ThreadResponse {
  parent_interaction: InteractionResponse;
  child_interactions: InteractionResponse[];
  ordered_thread: InteractionResponse[];
  reply_count: number;
  latest_interaction: InteractionResponse | null;
}

// GET /tickets/interactions
export interface TicketInteractionResponse extends InteractionResponse {
  ticket_title: string;
  client_company_name: string | null;
}

export interface InternalNoteRequest {
  subject: string;
  note: string;
  // Any active platform user, regardless of role/hierarchy — see
  // TicketComposer.tsx's UserMultiSelect "To" field. Optional: an
  // empty/omitted list falls back to the backend's pre-existing
  // stakeholder-notification behavior.
  recipient_user_ids?: string[];
  // Distribution Lists to include as note recipients, resolved to
  // their current active members and unioned into recipient_user_ids
  // at send time — same pattern RuleActionItem.distribution_list_ids
  // uses for forward_to.
  distribution_list_ids?: string[];
  // Optional sanitized-on-the-backend HTML counterpart to `note`
  // (Outlook-style clipboard paste) — internal notes are never
  // emailed, this only affects Timeline/System Mail rendering.
  body_html?: string | null;
  // See ReplyRequest.inline_image_interaction_ids above — same
  // meaning, same reason.
  inline_image_interaction_ids?: string[];
}

export interface InternalNoteResponse {
  interaction_id: string;
  ticket_id: string;
  message: string;
  created_at: string;
  recipient_user_ids?: string[];
  recipient_names?: string[];
}

// One eligible Internal Note "To" option — every active platform
// user, company-wide, regardless of role/reporting-hierarchy. Backed
// by GET /tickets/internal-notes/recipients, deliberately not RBAC's
// own GET /api/v1/users (hierarchy-scoped for Staff/Team Lead/Account
// Manager) or GET /api/v1/roles (role:view-gated, which Staff doesn't
// hold by default) — see that route's own docstring.
export interface InternalNoteRecipientCandidate {
  user_id: string;
  name: string;
  email: string;
  role_name: string;
}

export interface ReplyRequest {
  message: string;
  cc?: string[];
  bcc?: string[];
  // See InternalNoteRequest.distribution_list_ids above for the
  // general pattern — here, merged into `cc` server-side, never
  // `to_email`/`to_emails` (a reply always targets the real thread
  // participant(s)).
  distribution_list_ids?: string[];
  // Single-recipient override — still accepted by the backend for
  // back-compat callers (e.g. the ticket-detail Reply tab's own
  // separate, hand-rolled composer, TicketComposer.tsx). Mail's
  // ReplyComposer.tsx sends to_emails below instead.
  to_email?: string | null;
  // See InteractionReplyRequest.to_emails above — same override, same
  // reason. Mail's chip-based To field always sends this; when both
  // are given, the backend prefers to_emails.
  to_emails?: string[];
  // Points at the interaction_id an immediately-preceding
  // POST /tickets/{id}/attachments upload returned — set this so
  // those files are embedded in the actual outbound email, not just
  // recorded on the ticket's own timeline.
  attachment_source_interaction_id?: string | null;
  // See InteractionReplyRequest.reply_all above — same meaning, same
  // reason.
  reply_all?: boolean;
  // See InteractionReplyRequest.body_html above — same meaning, same
  // reason.
  body_html?: string | null;
  // Every interaction_id an inline-image-paste upload
  // (POST /tickets/{id}/attachments/inline-image) returned during
  // this compose session — each gets reassigned onto this reply's own
  // interaction and merged into the outbound envelope server-side
  // (see InteractionService._merge_inline_images_into_envelope).
  // Omit/empty when nothing was pasted.
  inline_image_interaction_ids?: string[];
  // See InteractionReplyRequest.idempotency_key above — same contract.
  idempotency_key?: string | null;
}

// ==========================================================
// Compose — brand-new outbound email, no prior thread
// ==========================================================

export interface ComposeEmailResponse {
  interaction_id: string;
  client_id: string | null;
  category_id: string | null;
  created_at: string;
  attachments: AttachmentMeta[];
  message: string;
}

// POST /inbox/{interaction_id}/forward — forwarding an existing
// client email to a mix of internal organization users, external
// addresses, and/or Distribution Lists, distinct from
// ComposeEmailResponse (which always addresses an external client
// contact from scratch). user_id is null for an external-email
// recipient (directly typed, or a source Distribution List had none
// to attribute).
export interface ForwardedRecipient {
  user_id: string | null;
  name: string | null;
  email: string;
}

export interface ForwardToInternalUserResponse {
  interaction_id: string;
  dispatch_status: string;
  created_at: string;
  recipients: ForwardedRecipient[];
}

export interface StatusChangeRequest {
  new_status: TicketStatus;
}

export interface PriorityChangeRequest {
  new_priority: TicketPriority;
}

export interface TicketActionResponse {
  interaction_id: string | null;
  ticket_id: string;
  message: string;
  created_at: string;
}

// Response for POST /interactions/{id}/cancel-send (Undo Send, Issue
// 8) — ticket_id is genuinely nullable here (reachable for a still-
// pending pre-ticket Compose/reply too), unlike TicketActionResponse's
// own required ticket_id.
export interface CancelSendResponse {
  interaction_id: string;
  ticket_id: string | null;
  message: string;
  created_at: string;
}

// POST /interactions/{id}/retry-send — Retry Send for a FAILED
// outbound Compose/Reply/Reply-All/Forward.
export interface RetrySendResponse {
  interaction_id: string;
  ticket_id: string | null;
  message: string;
  created_at: string;
}

export interface AttachmentUploadResponse {
  interaction_id: string;
  ticket_id: string;
  attachments: AttachmentMeta[];
  message: string;
}

export interface HideInteractionRequest {
  removed_by?: string | null;
}

export interface HideInteractionResponse {
  interaction_id: string;
  ticket_id: string | null;
  is_visible: boolean;
  removed_by: string | null;
  removed_at: string | null;
  message: string;
}

// ==========================================================
// Audit Log
//
// Immutable, write-once compliance/security record — distinct
// from Interaction (the visible ticket timeline). Never edited or
// deleted, so the frontend never renders any mutate action here.
// ==========================================================

export type AuditEntityType = "TICKET" | "INTERACTION" | "ATTACHMENT" | "CLIENT" | "USER";

export type AuditEventType =
  | "TICKET_CREATED"
  | "TICKET_UPDATED"
  | "TICKET_RESOLVED"
  | "STATUS_CHANGED"
  | "PRIORITY_CHANGED"
  | "AGENT_TRANSFERRED"
  | "CATEGORY_TRANSFERRED"
  | "INTERACTION_HIDDEN"
  | "ATTACHMENT_UPLOADED"
  | "NOTE_ADDED"
  | "REPLY_ADDED"
  | "EMAIL_RECEIVED"
  | "CLIENT_CREATED"
  | "TICKET_CLAIMED"
  | "INTERACTION_CLAIMED"
  | "INTERACTION_ARCHIVED"
  | "EDIT_ACCESS_REQUESTED"
  | "EDIT_ACCESS_APPROVED"
  | "EDIT_ACCESS_REJECTED"
  | "TICKET_CLOSED"
  | "TICKET_REOPENED"
  | "SLA_PAUSED"
  | "SLA_RESUMED"
  | "SLA_BREACH_DETECTED"
  | "SLA_ESCALATED"
  // Internal escalation workflow (TicketEscalation) — distinct from
  // SLA_ESCALATED above, which is the Resolution SLA's own
  // notification-ladder tier and never touches ownership/ack state.
  | "ESCALATION_CREATED"
  | "ESCALATION_ACKNOWLEDGED"
  | "ESCALATION_ADVANCED"
  | "ESCALATION_CLOSED";

export type ActorRole = "AGENT" | "CLIENT" | "SYSTEM";

export interface AuditLogResponse {
  audit_id: string;
  entity_type: AuditEntityType;
  entity_id: string;
  event_type: AuditEventType;
  actor_id: string | null;
  actor_name: string;
  actor_role: ActorRole;
  // Set only when this row was written during an active "Login as
  // User" impersonation session — the real, physically-authenticated
  // Super Admin, distinct from actor_id/actor_name above (which stay
  // whoever's identity actually governed the request). Undefined/null
  // for every ordinary row.
  impersonator_id?: string | null;
  impersonator_name?: string | null;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  created_at: string;
}

// GET /tickets/audit-logs
export interface TicketAuditLogResponse extends AuditLogResponse {
  ticket_id: string;
  ticket_title: string;
  // Null when the ticket has no client_company_id (legacy/unassigned
  // tickets).
  client_company_name: string | null;
}

// ==========================================================
// SLA
// ==========================================================

export type SLAClockStatus = "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED";

export interface ResolutionSLAState {
  status: SLAClockStatus;
  started_at: string;
  due_at: string;
  // The real target (in minutes) this clock is currently measured
  // against — read this directly rather than re-deriving a target
  // from priority, since once a handling stage has reshifted the
  // clock, its target no longer matches any single priority's flat
  // policy value (see the backend's ResolutionSLA.active_target_
  // minutes docstring).
  active_target_minutes: number;
  paused_at: string | null;
  total_paused_seconds: number;
  completed_at: string | null;
  elapsed_fraction: number;
}

export interface FirstResponseSLAState {
  status: SLAClockStatus;
  started_at: string;
  due_at: string;
  completed_at: string | null;
  completion_reason: string | null;
  elapsed_fraction: number;
}

// Internal escalation ownership/acknowledgment chain — entirely
// separate from (and never reflects a restart of) the Resolution SLA
// above. Routing follows the ticket's own assignment history now, not
// role hierarchy (see root CLAUDE.md's "SLA & Escalation" section):
// every non-terminal step is ASSIGNMENT_CHAIN; SITE_LEAD stays a real,
// literal terminal marker (the chain-exhausted Site Lead/Super Admin
// safety net). TEAM_LEAD/MANAGER are retired — kept only so old rows
// still deserialize, nothing writes them anymore.
export type EscalationLevel = "TEAM_LEAD" | "MANAGER" | "ASSIGNMENT_CHAIN" | "SITE_LEAD";
export type EscalationStatus = "ACTIVE" | "ACKNOWLEDGED" | "CLOSED";

export interface TicketEscalationState {
  escalation_id: string;
  level: EscalationLevel;
  status: EscalationStatus;
  owner_ids: string[];
  owner_names: string[];
  triggered_by: string;
  created_at: string;
  level_started_at: string;
  ack_due_at: string;
  acknowledged_at: string | null;
  closed_at: string | null;
  closed_reason: string | null;
  overdue_seconds: number;
  // Handling progression — independent of `level`/`status` above (see
  // root CLAUDE.md's SLA & Escalation section). 0 until the first
  // genuine acceptance completes; only advances on a real
  // accept-assign-breach cycle, never on an acknowledgment-window
  // ladder advance alone. handling_stage_due_at is null whenever no
  // stage is currently running (before the first acceptance, or
  // between a stage's breach and the next acceptance).
  handling_stage: number;
  handling_stage_started_at: string | null;
  handling_stage_due_at: string | null;
  // The ticket's real, pre-escalation priority — Ticket.current_priority
  // itself becomes (and permanently stays) CRITICAL once escalated, but
  // every actual SLA calculation (ack window, handling stages) is
  // resolved against this value, never CRITICAL's own policy row. Use
  // this, not the ticket's own current_priority, to look up which SLA
  // Timing Matrix row actually applies once an escalation exists.
  original_priority: TicketPriority;
}

// Internal escalation-handling clock — a second, wholly separate timer
// from `resolution` above, measuring time-to-actually-resolve once the
// current escalation owner has acknowledged (or been assigned) it.
// Its target is always 25% of the original Resolution SLA's configured
// target duration (see EscalationHandlingSlaService.compute_escalation_
// handling_target_seconds) — never derived from remaining/overdue time,
// and it never overwrites `resolution`'s own started_at/due_at/status.
export type EscalationHandlingSLAStatus = "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED";

export interface EscalationHandlingSLAState {
  status: EscalationHandlingSLAStatus;
  target_seconds: number;
  started_at: string;
  due_at: string;
  breached_at: string | null;
  completed_at: string | null;
  remaining_seconds: number;
}

// GET /tickets/{ticket_id}/sla — first_response is always null here by
// backend design (that clock lives on the originating interaction, not
// the ticket) — see SLAService.get_ticket_sla_state's own docstring.
export interface TicketSLAResponse {
  ticket_id: string;
  first_response: FirstResponseSLAState | null;
  resolution: ResolutionSLAState | null;
  escalation: TicketEscalationState | null;
  escalation_handling_sla: EscalationHandlingSLAState | null;
}

export interface SLAPolicyResponse {
  policy_id: string;
  priority: TicketPriority;
  first_response_target_minutes: number;
  resolution_target_minutes: number;
  escalation_ack_target_minutes: number;
  // Superseded by handling_stage_percentages below — no longer read by
  // any backend logic (kept only until the later EscalationHandlingSLA
  // cleanup phase). Don't use this for new UI.
  handling_sla_percentage: number;
  // Ordered, configurable per-stage percentages of the ticket's
  // ORIGINAL priority's resolution_target_minutes — index 0 is stage
  // 1's percentage, index 1 is stage 2's, etc. A stage beyond this
  // list's length repeats the last configured value.
  handling_stage_percentages: number[];
  warning_1_percentage: number;
  warning_2_percentage: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// PATCH /sla/policies/{id} — every field optional (partial update).
export interface SLAPolicyUpdatePayload {
  first_response_target_minutes?: number;
  resolution_target_minutes?: number;
  escalation_ack_target_minutes?: number;
  handling_sla_percentage?: number;
  handling_stage_percentages?: number[];
  warning_1_percentage?: number;
  warning_2_percentage?: number;
  is_active?: boolean;
}
