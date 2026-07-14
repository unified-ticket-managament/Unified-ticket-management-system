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

export type TicketPriority = "LOW" | "MEDIUM" | "HIGH";

// ==========================================================
// Categories — work-specialization categories (Eligibility, AR,
// Claims, ...) owned by the RBAC service; a ticket's `ticket_type`
// is one of these category names, fetched live via GET /categories
// rather than a fixed frontend enum.
// ==========================================================

export interface CategoryResponse {
  category_id: string;
  category_name: string;
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
  inbox_email: string;
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
}

// ==========================================================
// Agents
// ==========================================================

export interface AgentSummary {
  user_id: string;
  name: string;
  email: string;
}

// Who the current user may assign a brand-new ticket to on the
// Create Ticket dialog — see GET /agents/assignable, scoped per the
// caller's own role/hierarchy (AssignmentService on the backend).
export interface AssignableUserSummary {
  user_id: string;
  name: string;
}

export interface AssignableGroup {
  role: string;
  users: AssignableUserSummary[];
}

export interface AssignableAgentsResponse {
  me: AssignableUserSummary;
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
  to_email: string | null;
  from_email: string | null;
  from_name: string | null;
  cc: string[];
  bcc: string[];
  subject: string;
  body: string;
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
  draft_message: string | null;
  draft_cc: string[];
  draft_bcc: string[];
  draft_attachments: AttachmentMeta[];
  attachments?: AttachmentMeta[];
  replies: InteractionResponse[];
  recommended_ticket_id: string | null;
  recommended_ticket_reason: string | null;
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
  cc: string[];
  bcc: string[];
  attachments: AttachmentMeta[];
  created_at: string;
}

export interface DraftDeleteResponse {
  message: string;
}

export interface InteractionReplyRequest {
  message: string;
  cc?: string[];
  bcc?: string[];
  to_email?: string | null;
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
  created_at: string;
  updated_at: string;
  client_name: string | null;
  client_company_name: string | null;
  agent_name: string | null;
  created_by_name: string | null;
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

// ==========================================================
// Edit Access — request/approve/reject
// ==========================================================

export type EditAccessStatus = "PENDING" | "APPROVED" | "REJECTED";

export interface EditAccessRequestCreate {
  reason: string;
}

export interface EditAccessApproveRequest {
  expires_at?: string | null;
  review_note?: string | null;
}

export interface EditAccessRejectRequest {
  review_note?: string | null;
}

export interface EditAccessRequestResponse {
  request_id: string;
  ticket_id: string;
  requested_by: string;
  requested_by_name: string | null;
  reason: string;
  status: EditAccessStatus;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface TransferAgentRequest {
  new_agent_id: string;
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
}

export interface AttachInteractionResponse {
  message: string;
  ticket_id: string;
  interaction_id: string;
  status: InteractionStatus;
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
}

export interface InternalNoteResponse {
  interaction_id: string;
  ticket_id: string;
  message: string;
  created_at: string;
}

export interface ReplyRequest {
  message: string;
  cc?: string[];
  bcc?: string[];
  to_email?: string | null;
}

// ==========================================================
// Compose — brand-new outbound email, no prior thread
// ==========================================================

export interface ComposeEmailResponse {
  interaction_id: string;
  client_id: string;
  created_at: string;
  attachments: AttachmentMeta[];
  message: string;
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
  | "SLA_MANUALLY_PAUSED"
  | "SLA_MANUALLY_RESUMED"
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
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  created_at: string;
}

// GET /tickets/audit-logs
export interface TicketAuditLogResponse extends AuditLogResponse {
  ticket_id: string;
  ticket_title: string;
}

// ==========================================================
// SLA
// ==========================================================

export type SLAClockStatus = "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED";

export interface ResolutionSLAState {
  status: SLAClockStatus;
  started_at: string;
  due_at: string;
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
// above. TEAM_LEAD is always the first level; SITE_LEAD is terminal.
export type EscalationLevel = "TEAM_LEAD" | "MANAGER" | "SITE_LEAD";
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
  is_active: boolean;
  created_at: string;
  updated_at: string;
}
