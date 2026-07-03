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
// Email
// ==========================================================

export interface EmailRequest {
  from_email: string;
  subject: string;
  body: string;
  message_id: string;
}

export interface EmailResponse {
  message: string;
  interaction_id: string;
  client_name: string;
  agent_name: string;
  status: string;
  attachments?: AttachmentMeta[];
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
// Agent Inbox
// ==========================================================

export interface InboxItem {
  interaction_id: string;
  client_name: string;
  subject: string;
  message_id: string | null;
  received_at: string;
  status: InteractionStatus;
  has_attachments: boolean;
}

export interface InboxResponse {
  total: number;
  items: InboxItem[];
}

export interface OpenEmailResponse {
  interaction_id: string;
  client_name: string;
  agent_name: string;
  from_email: string;
  subject: string;
  body: string;
  message_id: string | null;
  received_at: string;
  status: InteractionStatus;
  attachments?: AttachmentMeta[];
}

// ==========================================================
// Ticket
// ==========================================================

export interface TicketResponse {
  ticket_id: string;
  client_id: string;
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

export interface ResolveTicketRequest {
  resolution_note?: string | null;
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
  | "EMAIL_RECEIVED";

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
