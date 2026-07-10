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

export type InboxView = "pending" | "replied" | "ticketed" | "archived" | "snoozed" | "all";
export type InboxScope = "mine" | "all";

export interface InboxItem {
  interaction_id: string;
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
  snoozed_until: string | null;
  reply_count: number;
  latest_message: string | null;
  latest_sender: string | null;
  latest_at: string | null;
}

export interface InboxResponse {
  total: number;
  items: InboxItem[];
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
  snoozed_until: string | null;
  draft_message: string | null;
  draft_cc: string[];
  draft_bcc: string[];
  draft_attachments: AttachmentMeta[];
  attachments?: AttachmentMeta[];
  replies: InteractionResponse[];
  recommended_ticket_id: string | null;
  recommended_ticket_reason: string | null;
}

export interface InteractionSnoozeResponse {
  interaction_id: string;
  snoozed_until: string | null;
  message: string;
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
  interaction_id: string;
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
  | "EDIT_ACCESS_REJECTED";

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
