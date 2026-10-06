import { apiClient } from "./client";
import type { MailFolder } from "@tw/types";

// GET /folders — every custom mail folder, ordered by name.
export async function listMailFolders(): Promise<MailFolder[]> {
  const { data } = await apiClient.get<MailFolder[]>("/folders");
  return data;
}

// POST /folders — create a new custom folder (root when parentFolderId
// is null/omitted, otherwise a subfolder).
export async function createMailFolder(
  name: string,
  parentFolderId: string | null = null
): Promise<MailFolder> {
  const { data } = await apiClient.post<MailFolder>("/folders", {
    name,
    parent_folder_id: parentFolderId,
  });
  return data;
}

// PATCH /folders/{folder_id} — rename (id and contents are unchanged).
export async function renameMailFolder(folderId: string, name: string): Promise<MailFolder> {
  const { data } = await apiClient.patch<MailFolder>(`/folders/${folderId}`, { name });
  return data;
}

// PATCH /folders/{folder_id}/parent — move under another folder, or to
// root with null. Subfolders travel with it.
export async function moveMailFolder(
  folderId: string,
  parentFolderId: string | null
): Promise<MailFolder> {
  const { data } = await apiClient.patch<MailFolder>(`/folders/${folderId}/parent`, {
    parent_folder_id: parentFolderId,
  });
  return data;
}

// DELETE /folders/{folder_id}
export async function deleteMailFolder(folderId: string): Promise<void> {
  await apiClient.delete(`/folders/${folderId}`);
}
