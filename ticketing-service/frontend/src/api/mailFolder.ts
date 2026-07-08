import { apiClient } from "./client";
import type { MailFolder } from "@/types";

// GET /folders — every custom mail folder, ordered by name.
export async function listMailFolders(): Promise<MailFolder[]> {
  const { data } = await apiClient.get<MailFolder[]>("/folders");
  return data;
}

// POST /folders — create a new custom folder.
export async function createMailFolder(name: string): Promise<MailFolder> {
  const { data } = await apiClient.post<MailFolder>("/folders", { name });
  return data;
}

// DELETE /folders/{folder_id}
export async function deleteMailFolder(folderId: string): Promise<void> {
  await apiClient.delete(`/folders/${folderId}`);
}
