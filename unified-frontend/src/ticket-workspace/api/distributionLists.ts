import { apiClient } from "./client";

// Distribution Lists (internal groups) — see
// unified-backend/app/ticketing/schemas/distribution_list.py for the
// matching Pydantic shapes. Two independently-gated surfaces:
// - Admin CRUD (list/get/create/update/active/members/delete), gated
//   on rule:manage server-side.
// - `listActiveDistributionLists()` below, the one shared "recipient
//   selection" listing every picker across the app calls (Forward,
//   Compose, Mail Reply, Ticket Reply, Internal Note, Rules'
//   forward_to) — gated only by authentication, deliberately NOT
//   rule:manage/rule:view_all.

export interface DistributionListMemberSummary {
  user_id: string;
  name: string;
  email: string;
}

export interface DistributionListSummaryResponse {
  distribution_list_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_by: string | null;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface DistributionListResponse {
  distribution_list_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  members: DistributionListMemberSummary[];
}

export interface DistributionListRecipientCandidate {
  distribution_list_id: string;
  name: string;
  description: string | null;
  member_count: number;
}

export interface DistributionListCreatePayload {
  name: string;
  description?: string | null;
  member_user_ids: string[];
}

export interface DistributionListUpdatePayload {
  name: string;
  description?: string | null;
  is_active: boolean;
}

// The one shared endpoint every recipient picker in the app calls —
// see this file's own top-of-file note.
export async function listActiveDistributionLists(
  signal?: AbortSignal
): Promise<DistributionListRecipientCandidate[]> {
  const { data } = await apiClient.get<{ distribution_lists: DistributionListRecipientCandidate[] }>(
    "/distribution-lists/active",
    { signal }
  );
  return data.distribution_lists;
}

// Admin CRUD — every call below is gated on rule:manage server-side.

export async function listDistributionLists(
  signal?: AbortSignal
): Promise<DistributionListSummaryResponse[]> {
  const { data } = await apiClient.get<DistributionListSummaryResponse[]>("/distribution-lists", {
    signal,
  });
  return data;
}

export async function getDistributionList(id: string): Promise<DistributionListResponse> {
  const { data } = await apiClient.get<DistributionListResponse>(`/distribution-lists/${id}`);
  return data;
}

export async function createDistributionList(
  payload: DistributionListCreatePayload
): Promise<DistributionListResponse> {
  const { data } = await apiClient.post<DistributionListResponse>("/distribution-lists", payload);
  return data;
}

export async function updateDistributionList(
  id: string,
  payload: DistributionListUpdatePayload
): Promise<DistributionListResponse> {
  const { data } = await apiClient.put<DistributionListResponse>(`/distribution-lists/${id}`, payload);
  return data;
}

export async function setDistributionListActive(
  id: string,
  isActive: boolean
): Promise<DistributionListResponse> {
  const { data } = await apiClient.patch<DistributionListResponse>(`/distribution-lists/${id}/active`, {
    is_active: isActive,
  });
  return data;
}

export async function addDistributionListMember(
  id: string,
  userId: string
): Promise<DistributionListResponse> {
  const { data } = await apiClient.post<DistributionListResponse>(`/distribution-lists/${id}/members`, {
    user_id: userId,
  });
  return data;
}

export async function removeDistributionListMember(
  id: string,
  userId: string
): Promise<DistributionListResponse> {
  const { data } = await apiClient.delete<DistributionListResponse>(
    `/distribution-lists/${id}/members/${userId}`
  );
  return data;
}

export async function deleteDistributionList(id: string): Promise<void> {
  await apiClient.delete(`/distribution-lists/${id}`);
}
