import { apiClient } from "./client";
import type { TicketAssignmentsResponse, TicketStatus } from "@tw/types";

// Multi-user / multi-category assignment endpoints. Every call returns
// the ticket's full, fresh assignment state so the UI never has to
// patch local state by hand. The backend re-validates everything
// (users, primary choice, permissions) — nothing sent here is trusted.

// GET /tickets/{ticket_id}/assignments
export async function getTicketAssignments(
  ticketId: string
): Promise<TicketAssignmentsResponse> {
  const { data } = await apiClient.get<TicketAssignmentsResponse>(
    `/tickets/${ticketId}/assignments`
  );
  return data;
}

// POST /tickets/{ticket_id}/assignments — all-or-nothing.
export async function assignTicketUsers(
  ticketId: string,
  userIds: string[],
  primaryUserId?: string | null
): Promise<TicketAssignmentsResponse> {
  const { data } = await apiClient.post<TicketAssignmentsResponse>(
    `/tickets/${ticketId}/assignments`,
    { user_ids: userIds, primary_user_id: primaryUserId ?? null }
  );
  return data;
}

// PATCH /tickets/{ticket_id}/assignments/{assignment_id}
export async function updateTicketAssignment(
  ticketId: string,
  assignmentId: string,
  payload: { status?: TicketStatus; is_primary?: true }
): Promise<TicketAssignmentsResponse> {
  const { data } = await apiClient.patch<TicketAssignmentsResponse>(
    `/tickets/${ticketId}/assignments/${assignmentId}`,
    payload
  );
  return data;
}

// DELETE /tickets/{ticket_id}/assignments/{assignment_id}
export async function removeTicketAssignment(
  ticketId: string,
  assignmentId: string,
  newPrimaryAssignmentId?: string | null
): Promise<TicketAssignmentsResponse> {
  const { data } = await apiClient.delete<TicketAssignmentsResponse>(
    `/tickets/${ticketId}/assignments/${assignmentId}`,
    {
      params: newPrimaryAssignmentId
        ? { new_primary_assignment_id: newPrimaryAssignmentId }
        : undefined,
    }
  );
  return data;
}

// POST /tickets/{ticket_id}/categories
export async function addTicketCategory(
  ticketId: string,
  categoryId: string
): Promise<TicketAssignmentsResponse> {
  const { data } = await apiClient.post<TicketAssignmentsResponse>(
    `/tickets/${ticketId}/categories`,
    { category_id: categoryId }
  );
  return data;
}

// DELETE /tickets/{ticket_id}/categories/{category_id}
export async function removeTicketCategory(
  ticketId: string,
  categoryId: string
): Promise<TicketAssignmentsResponse> {
  const { data } = await apiClient.delete<TicketAssignmentsResponse>(
    `/tickets/${ticketId}/categories/${categoryId}`
  );
  return data;
}
