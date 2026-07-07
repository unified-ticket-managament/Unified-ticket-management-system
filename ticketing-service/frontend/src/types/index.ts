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
}

// ==========================================================
// Account Manager Inbox
// ==========================================================

export type InboxView = "pending" | "replied" | "ticketed" | "archived" | "all";
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
  has_attachments: boolean;
  claimed_by: string | null;
  claimed_by_name: string | null;
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
  subject: string;
  body: string;
  message_id: string | null;
  received_at: string;
  status: InteractionStatus;
  claimed_by: string | null;
  claimed_by_name: string | null;
  attachments?: AttachmentMeta[];
  replies: InteractionResponse[];
}

export interface InteractionReplyRequest {
  message: string;
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
  | "INTERACTION_CLAIMED"
  | "INTERACTION_ARCHIVED";

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
