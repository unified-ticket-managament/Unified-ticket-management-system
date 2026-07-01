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
}

// ==========================================================
// Ticket
// ==========================================================

export interface TicketResponse {
  ticket_id: string;
  client_id: string;
  agent_id: string | null;
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

export interface AttachmentUploadRequest {
  filename: string;
  mime_type?: string | null;
  size_bytes?: number | null;
  storage_key: string;
  scan_status?: string;
  performed_by?: string | null;
}

export interface AttachmentUploadResponse {
  interaction_id: string;
  attachment_id: string;
  ticket_id: string;
  filename: string;
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
